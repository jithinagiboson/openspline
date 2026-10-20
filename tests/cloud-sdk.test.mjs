import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {WebSocketServer} from 'ws';
import {Openspline} from '../packages/node/dist/index.js';

async function gateway(t, fail=false, invalidEndpoint=false) {
  const requests=[];let base;
  const server=createServer(async(req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;
    requests.push({path:req.url,method:req.method,token:req.headers.authorization,body});
    res.setHeader('Content-Type','application/json');
    if(req.url==='/api/v1/sessions')res.end(JSON.stringify({id:'cloud-id',url:invalidEndpoint?'http://insecure.invalid':base,publisher_token:'publisher-secret',cloud:true,transport:'websocket'}));
    else if(req.method==='DELETE'){res.statusCode=204;res.end();}
    else if(req.url.endsWith('/interrupt'))res.end(JSON.stringify({epoch:1}));
    else if(req.url.endsWith('/viewer'))res.end(JSON.stringify({id:'cloud-id',url:base,token:'rotated-viewer',viewer_url:base+'/view#safe',transport:'websocket',usageToken:'never-public'}));
    else if(req.url.endsWith('/livekit'))res.end(JSON.stringify({connected:true}));
    else {res.statusCode=404;res.end('{}');}
  });
  const wss=new WebSocketServer({server});
  const audio=[];
  wss.on('connection',ws=>ws.on('message',raw=>{
    const event=JSON.parse(raw);
    if(event.token){assert.equal(event.token,'publisher-secret');if(fail){ws.send(JSON.stringify({type:'error',code:'inference',message:'Warmup failed'}));return;}
      ws.send(JSON.stringify({type:'session',session:{id:'cloud-id',url:base,token:'viewer-only',viewer_url:base+'/view#safe',expires_at:9999999999,transport:'websocket',publisher_token:'never-public'}}));
      ws.send(JSON.stringify({type:'viewer_ready'}));
    }else{audio.push(event);ws.send(JSON.stringify({type:'ack',id:event.id}));}
  }));
  server.listen(0,'127.0.0.1');await once(server,'listening');base=`http://127.0.0.1:${server.address().port}`;
  t.after(async()=>{for(const ws of wss.clients)ws.terminate();await new Promise(resolve=>wss.close(resolve));await new Promise(resolve=>server.close(resolve));});
  return {base,requests,audio};
}
test('API keys select Cloud and are omitted from serialized configuration',()=>{
  const old=process.env.OPENSPLINE_URL;delete process.env.OPENSPLINE_URL;
  try {const c=new Openspline({apiKey:'account-secret'});assert.equal(c.url,'https://dashboard.openspline.dev/api');assert.ok(!JSON.stringify(c.config).includes('account-secret'));}
  finally {if(old!==undefined)process.env.OPENSPLINE_URL=old;}
});
test('Node Cloud sessions initialize, stream, interrupt and clean up with separated credentials',async(t)=>{
  const g=await gateway(t),client=new Openspline({apiKey:'account-secret',url:g.base+'/api',timeout:2000});
  const avatar=await client.avatar({avatarId:'saved-avatar'},{quality:'high'});
  assert.equal(avatar.session.transport,'websocket');assert.equal(avatar.session.publisher_token,undefined);
  assert.match(g.requests[0].body,/saved-avatar/);assert.match(g.requests[0].body,/high/);
  await avatar.sendAudio(Buffer.alloc(4800));await avatar.endTurn();await avatar.interrupt();assert.equal(avatar.epoch,1);
  await avatar.viewer();assert.equal(avatar.session.usageToken,undefined);
  await avatar.close();await avatar.close();
  for(const r of g.requests)assert.equal(r.token,r.path.startsWith('/api/')?'Bearer account-secret':'Bearer publisher-secret');
  assert.equal(g.requests.filter(r=>r.path==='/api/v1/sessions/cloud-id'&&r.method==='DELETE').length,1);
  assert.equal(g.audio.find(e=>e.type==='audio').format.sample_rate,24000);
});
test('Cloud initialization failure preserves the error and releases the account reservation',async(t)=>{
  const g=await gateway(t,true),client=new Openspline({apiKey:'account-secret',url:g.base+'/api',timeout:2000});
  await assert.rejects(client.avatar(Buffer.from('portrait')),/Warmup failed/);
  assert.ok(g.requests.some(r=>r.path==='/api/v1/sessions/cloud-id'&&r.method==='DELETE'));
});
test('Invalid Cloud endpoints are rejected and their reservations released',async(t)=>{
  const g=await gateway(t,false,true),client=new Openspline({apiKey:'account-secret',url:g.base+'/api',timeout:2000});
  await assert.rejects(client.avatar(Buffer.from('portrait')),/invalid session endpoint/);
  assert.ok(g.requests.some(r=>r.path==='/api/v1/sessions/cloud-id'&&r.method==='DELETE'));
});
