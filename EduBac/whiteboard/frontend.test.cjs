'use strict';
// Dependency-free frontend regression tests: node --test EduBac/whiteboard/frontend.test.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const model = require('../static/js/whiteboard-objects.js');
const source = name => fs.readFileSync(path.join(__dirname, '../static/js/', name), 'utf8');
const flush = async () => { for (let i=0;i<12;i++) await Promise.resolve(); };

const samples = () => [
  {type:'stroke',points:[{x:10,y:10},{x:40,y:40}],size:4,color:'#352443'},
  {type:'line',x1:100,y1:100,x2:150,y2:130},
  {type:'arrow',x1:200,y1:100,x2:250,y2:130},
  {type:'rect',x:300,y:100,w:60,h:50},
  {type:'circle',cx:440,cy:130,r:30},
  {type:'triangle',x1:500,y1:150,x2:560,y2:150,x3:530,y3:100},
  {type:'text',text:'2x + 5 = 13',x:600,y:130,size:4},
  {type:'math',latex:'x=4',x:900,y:100},
  {type:'graph',expr:'x*x',xmin:-5,xmax:5,x:100,y:250,w:300,h:200},
  {type:'image',src:'data:image/png;base64,aGVsbG8=',x:500,y:250,w:80,h:60},
  {type:'note',text:'On soustrait 5.',x:700,y:280,size:3}
];
test('legacy ids are deterministic, unique and preserved across saves', () => {
  const first=model.normalize(samples()), second=model.normalize(samples());
  assert.deepEqual(first.map(o=>o.id),second.map(o=>o.id));
  assert.equal(new Set(first.map(o=>o.id)).size,first.length);
  assert.deepEqual(model.normalize(JSON.parse(model.state(first))).map(o=>o.id),first.map(o=>o.id));
  first.push({...first[0]});
  model.normalize(first);
  assert.equal(new Set(first.map(o=>o.id)).size,first.length);
});
test('every existing type plus tutor notes has bounds, hit-testing and translation', () => {
  const points=[{x:25,y:25},{x:125,y:115},{x:225,y:115},{x:320,y:120},{x:440,y:130},{x:530,y:130},{x:620,y:120},{x:920,y:110},{x:200,y:300},{x:520,y:270},{x:730,y:275}];
  samples().forEach((o,i)=>{
    assert.equal(model.hit(o,points[i]),true,o.type+' is selectable');
    const before=model.bounds(o);
    model.move(o,33,-17);
    const after=model.bounds(o);
    assert.equal(after.x,before.x+33,o.type+' moves horizontally');
    assert.equal(after.y,before.y-17,o.type+' moves vertically');
    assert.equal(model.hit(o,{x:points[i].x+33,y:points[i].y-17}),true);
  });
  assert.equal(model.hit(samples()[0],{x:10,y:40},2),false,'stroke hit testing follows actual path, not just bounding box');
});
test('serialized undo snapshots preserve images and omit DOM/function caches', () => {
  const objects=samples();
  objects[9]._img={cyclic:'browser image'};
  objects[8]._fn=x=>x*x;
  objects[8]._width=100;
  const snapshot=model.state(objects);
  assert.equal(JSON.parse(snapshot)[9].src,objects[9].src);
  assert.equal(snapshot.includes('_img'),false);
  assert.equal(snapshot.includes('_fn'),false);
  assert.equal(snapshot.includes('_width'),false);
});
test('AI actions allow content only, keep math schema, wrap notes, and do not overlap', () => {
  const existing=[{type:'rect',x:0,y:0,w:1500,h:600}];
  const added=model.actions([
    {action:'eval',content:'alert(1)'},
    {action:'add_equation',content:'x = 4',x:0,y:0,type:'script'},
    {action:'add_text',content:'<img src=x onerror=alert(1)>',javascript:'alert(1)'},
    {action:'add_note',content:'Une règle à vérifier. '.repeat(30)},
    {action:'add_note',content:23}
  ],existing,1600);
  assert.equal(added.length,3);
  assert.equal(added[0].type,'math');
  assert.equal(added[0].latex,'x = 4');
  assert.equal(added[1].text,'<img src=x onerror=alert(1)>');
  assert.equal(added[2].type,'text');
  assert.equal(added[2].note,true,'notes extend the existing text schema');
  assert.equal(added[2].text.includes('\n'),true);
  added.forEach(o=>assert.equal('javascript' in o,false));
  const boxes=existing.concat(added).map(model.bounds);
  for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
    const a=boxes[i],b=boxes[j];
    assert.equal(a.x<b.x+b.w && a.x+a.w>b.x && a.y<b.y+b.h && a.y+a.h>b.y,false);
  }
});

class Element {
  constructor(tag='div') {
    this.tagName=tag.toUpperCase();this.children=[];this.events={};this.dataset={};this.style={};this.attrs={};
    this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.parentNode=null;
    this.clientWidth=1600;this.clientHeight=1000;this.offsetWidth=100;this.offsetHeight=40;
    this.width=1600;this.height=1000;this.files=[];this.scrollHeight=500;this.scrollTop=0;this.open=false;
    const classes=new Set();
    this.classList={add:s=>classes.add(s),remove:s=>classes.delete(s),contains:s=>classes.has(s)};
  }
  addEventListener(name,fn){(this.events[name] ||= []).push(fn);}
  emit(name,event={}){for(const fn of this.events[name] || [])fn({target:this,preventDefault(){},...event});}
  setAttribute(name,value){this.attrs[name]=String(value);}
  getAttribute(name){return this.attrs[name] || null;}
  removeAttribute(name){delete this.attrs[name];}
  appendChild(child){this.children.push(child);child.parentNode=this;return child;}
  replaceChildren(){this.children=[];}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(c=>c!==this);}
  focus(){this.focused=true;}
  click(){this.emit('click');}
  showModal(){this.open=true;}
  close(){this.open=false;}
  setPointerCapture(id){this.captured=id;}
  hasPointerCapture(id){return this.captured===id;}
  releasePointerCapture(){this.captured=null;}
  getBoundingClientRect(){return {left:0,top:0,width:1600,height:1000};}
  toDataURL(){return 'data:image/png;base64,aGVsbG8=';}
}
function harness({edit=true,objects=samples(),tutor=false,saveStatus=200,pointer=false,student=false}={}) {
  const elements=new Map();
  function get(id){
    if(!elements.has(id)){
      const element=new Element(id.includes('Input')?'input':'div');
      if(['wbTutor','wbTutorAttachment','wbTutorError','wbTutorLoading','wbLoadError','wbSelectionBar'].includes(id))element.hidden=true;
      elements.set(id,element);
    }
    return elements.get(id);
  }
  get('wbApp').dataset={boardId:'7',canEdit:edit?'1':'0',isStudent:student?'1':'0',apiUrl:'/tableau/7/api/',tutorUrl:'/tableau/7/tutor/',csrf:'csrf-test',wsPath:'/ws/7/'};
  const tools=['select','pencil','pen','highlighter','eraser','text','line','arrow','rect','circle','triangle','ruler','protractor'].map(tool=>{const e=new Element('button');e.dataset.tool=tool;return e;});
  const modes=['hint','explanation','solution'].map(mode=>{const e=new Element('button');e.dataset.mode=mode;return e;});
  const intents=['explain','hint','verify','solve','rule'].map(intent=>{const e=new Element('button');e.dataset.tutorIntent=intent;return e;});
  const globalEvents={}, requests=[], answers=[];
  const document={
    getElementById:get,
    createElement:tag=>new Element(tag),
    createTextNode:text=>Object.assign(new Element('#text'),{textContent:text}),
    addEventListener(name,fn){(globalEvents[name] ||= []).push(fn);},
    querySelectorAll(selector){
      if(selector==='.wb-tool[data-tool]' || selector==='.wb-tool')return tools;
      if(selector==='[data-mode]')return modes;
      if(selector==='[data-tutor-intent]')return intents;
      if(selector==='#wbEditorFields [name]')return get('wbEditorFields').children.map(c=>c.children[0]);
      return [];
    }
  };
  const noop=()=>{};
  const strokes=[], drawnText=[];
  let trace=[];
  get('wbCanvas').getContext=()=>new Proxy({
    getImageData:()=>({}),measureText:text=>({width:text.length*17}),
    beginPath:()=>{trace=[];},moveTo:(x,y)=>trace.push({x,y}),lineTo:(x,y)=>trace.push({x,y}),
    stroke:()=>strokes.push(trace.slice()),fillText:(text,x,y)=>drawnText.push({text,x,y})
  },{get:(obj,key)=>obj[key] || noop,set:(obj,key,value)=>{obj[key]=value;return true;}});
  let savedObjects;
  const context={
    document,console,EduBacObjects:model,CustomEvent:class {constructor(type,options){this.type=type;this.detail=options?.detail;}},
    Event:class {constructor(type){this.type=type;}},Image:class {set src(value){this.value=value;}},
    WebSocket:class {constructor(){this.readyState=1;}send(){}},
    location:{protocol:'http:',host:'example.test'},confirm:()=>true,prompt:()=>null,
    setTimeout:()=>1,clearTimeout:noop,AbortController,
    fetch:async(url,options)=>{
      requests.push({url,options});
      if(options?.method==='POST' && url.endsWith('/api/')){
        savedObjects=JSON.parse(options.body).content.objects;
        return {ok:saveStatus===200,status:saveStatus,json:async()=>({})};
      }
      if(url.endsWith('/tutor/')) {
        const answer=answers.shift() || {reply:'Indice : isole le terme en x.',actions:[],can_edit:edit};
        if(answer instanceof Error)throw answer;
        return {ok:!answer.status,status:answer.status || 200,json:async()=>answer};
      }
      return {ok:true,json:async()=>({content:{objects:JSON.parse(JSON.stringify(objects))}})};
    },
    addEventListener(name,fn){(globalEvents[name] ||= []).push(fn);},
    dispatchEvent(e){for(const fn of globalEvents[e.type] || [])fn(e);}
  };
  context.window=context;
  if(pointer)context.PointerEvent=class {};
  vm.createContext(context);vm.runInContext(source('whiteboard.js'),context);
  if(tutor)vm.runInContext(source('whiteboard-tutor.js'),context);
  return {get,tools,modes,intents,context,requests,answers,strokes,drawnText,saved:()=>savedObjects,
    emit:(type,event={})=>{for(const fn of globalEvents[type] || [])fn({preventDefault(){},...event});}};
}
test('board selects, drags, edits and deletes objects; undo/redo restore images; actions are one batch and persist',async()=>{
  const h=harness();await flush();
  h.tools[0].click();
  h.get('wbCanvas').emit('mousedown',{clientX:520,clientY:270});
  const selected=h.context.EduBacBoard.getSelected();assert.equal(selected.type,'image');
  h.get('wbCanvas').emit('mousemove',{clientX:540,clientY:280});
  h.get('wbCanvas').emit('mouseup',{clientX:540,clientY:280});
  assert.equal(h.context.EduBacBoard.getSelected().x,520);
  h.get('wbUndo').click();assert.equal(h.context.EduBacBoard.getSelected().x,500);
  assert.equal(h.context.EduBacBoard.getSelected().src,selected.src);
  h.get('wbRedo').click();assert.equal(h.context.EduBacBoard.getSelected().x,520);
  h.get('wbEditSelected').click();assert.equal(h.get('wbObjectEditor').open,true);
  const w=h.get('wbEditorFields').children.flatMap(c=>c.children).find(input=>input.name==='w');
  w.value='125';h.get('wbEditorForm').emit('submit');
  assert.equal(h.context.EduBacBoard.getSelected().w,125);
  h.get('wbDeleteSelected').click();assert.equal(h.context.EduBacBoard.getSelected(),null);
  h.get('wbUndo').click();assert.equal(h.context.EduBacBoard.getObjects().find(o=>o.id===selected.id).src,selected.src);
  const count=h.context.EduBacBoard.getObjects().length;
  const added=h.context.EduBacBoard.addActions([{action:'add_equation',content:'x=4'},{action:'add_note',content:'On divise par deux.'}]);
  assert.equal(added.length,2);
  h.get('wbUndo').click();assert.equal(h.context.EduBacBoard.getObjects().length,count);
  h.get('wbRedo').click();assert.equal(h.context.EduBacBoard.getObjects().length,count+2);
  h.get('wbSaveBtn').click();await flush();
  assert.equal(h.saved().length,count+2);
  assert.equal(h.saved().find(o=>o.id===selected.id).src,selected.src);
  assert.equal(h.saved().some(o=>'_img' in o),false);
});
test('read-only can select but cannot draw, drag, edit, delete, undo or apply tutor actions',async()=>{
  const h=harness({edit:false});await flush();
  const before=JSON.stringify(h.context.EduBacBoard.getObjects());
  h.get('wbCanvas').emit('mousedown',{clientX:920,clientY:110});
  assert.equal(h.context.EduBacBoard.getSelected().type,'math');
  h.get('wbCanvas').emit('mousemove',{clientX:950,clientY:150});
  h.get('wbCanvas').emit('mouseup',{clientX:950,clientY:150});
  h.get('wbEditSelected').click();h.get('wbDeleteSelected').click();h.get('wbUndo').click();
  assert.equal(h.get('wbObjectEditor').open,false);
  assert.equal(h.context.EduBacBoard.addActions([{action:'add_note',content:'test'}]).length,0);
  assert.equal(JSON.stringify(h.context.EduBacBoard.getObjects()),before);
});
function textOf(node){return node.textContent+(node.children || []).map(textOf).join('');}
test('selected hint → verification → solution uses CSRF endpoint, context, modes and whitelisted editable actions',async()=>{
  const h=harness({tutor:true});await flush();
  h.tools[0].click();h.get('wbCanvas').emit('mousedown',{clientX:920,clientY:110});h.get('wbCanvas').emit('mouseup');
  h.intents[1].click();await flush();
  const first=h.requests.find(r=>r.url.endsWith('/tutor/'));
  assert.equal(first.url,'/tableau/7/tutor/');
  assert.equal(first.options.credentials,'same-origin');
  assert.equal(first.options.headers['X-CSRFToken'],'csrf-test');
  const p=JSON.parse(first.options.body);
  assert.equal(p.mode,'hint');assert.equal(p.intent,'hint');
  assert.equal(p.selected_id,h.context.EduBacBoard.getSelected().id);
  assert.equal(p.objects.find(o=>o.id===p.selected_id).latex,'x=4');
  h.answers.push({reply:'Revois la soustraction.',can_edit:true,actions:[],verification:{correct:false,error_step:'2',reason:'Les deux membres doivent changer.',review_step:'Soustraire 5.',rule:'a=b implique a-c=b-c.'},context:{niveau:'1ère Bac',lesson:'Équations'}});
  h.intents[2].click();await flush();
  assert.match(textOf(h.get('wbTutorLog')),/Les deux membres doivent changer/);
  assert.match(h.get('wbTutorLesson').textContent,/1ère Bac/);
  h.answers.push({reply:'La solution est $x=4$.',can_edit:true,actions:[{action:'add_equation',content:'x=4'},{action:'add_note',content:'On divise les deux membres par 2.'},{action:'execute',content:'alert(1)'}]});
  h.intents[3].click();await flush();
  const request=JSON.parse(h.requests.filter(r=>r.url.endsWith('/tutor/')).at(-1).options.body);
  assert.equal(request.mode,'solution');assert.equal(request.intent,'solve');
  assert.equal(request.previous_attempts[0],'x=4');assert.equal(request.history.length,4);
  const last=h.get('wbTutorLog').children.at(-1);
  const add=last.children.find(c=>c.tagName==='BUTTON');
  const count=h.context.EduBacBoard.getObjects().length;add.click();
  assert.equal(h.context.EduBacBoard.getObjects().length,count+2);
  assert.equal(add.disabled,true);
});
test('errors retain question, retry exact request; successful in-flight edits are retained',async()=>{
  const h=harness({tutor:true});await flush();
  h.answers.push({status:429,error:'Patiente avant de réessayer.'});
  h.get('wbTutorQuestion').value='Je ne comprends pas.';
  h.get('wbTutorForm').emit('submit');await flush();
  assert.equal(h.get('wbTutorQuestion').value,'Je ne comprends pas.');
  assert.equal(h.get('wbTutorError').hidden,false);
  const original=h.requests.at(-1).options.body;
  h.get('wbTutorQuestion').value='Une nouvelle question.';
  h.get('wbTutorRetry').click();await flush();
  assert.equal(h.requests.at(-1).options.body,original);
  assert.equal(h.get('wbTutorQuestion').value,'Une nouvelle question.');
  h.get('wbTutorForm').emit('submit');
  h.get('wbTutorQuestion').value='Texte écrit pendant la réponse';
  await flush();assert.equal(h.get('wbTutorQuestion').value,'Texte écrit pendant la réponse');
});
test('selected images automatically attach; snapshots require explicit confirmation; no reply HTML is interpreted',async()=>{
  const h=harness({tutor:true});await flush();
  h.tools[0].click();h.get('wbCanvas').emit('mousedown',{clientX:520,clientY:270});h.get('wbCanvas').emit('mouseup');
  h.get('wbTutorQuestion').value='Explique cette image.';
  h.answers.push({reply:'<script>bad()</script>',actions:[],can_edit:false});
  h.get('wbTutorForm').emit('submit');await flush();
  assert.equal(JSON.parse(h.requests.at(-1).options.body).image,'data:image/png;base64,aGVsbG8=');
  assert.equal(JSON.parse(h.requests.at(-1).options.body).objects.some(o=>'src' in o || '_img' in o || 'data' in o),false);
  assert.match(textOf(h.get('wbTutorLog')),/<script>bad\(\)<\/script>/);
  assert.equal(h.get('wbTutorLog').children.at(-1).children.find(c=>c.tagName==='BUTTON').disabled,true);
  h.context.confirm=()=>false;h.get('wbTutorSnapshot').click();assert.equal(h.get('wbTutorAttachment').hidden,true);
  assert.equal(h.get('wbTutorThumbnail').src,undefined);
  h.context.confirm=()=>true;h.get('wbTutorSnapshot').click();assert.equal(h.get('wbTutorThumbnail').src,'data:image/png;base64,aGVsbG8=');
});
test('failed save cannot claim success or discard local objects',async()=>{
  const h=harness({saveStatus:403});await flush();
  const before=JSON.stringify(h.context.EduBacBoard.getObjects());
  h.get('wbSaveBtn').click();await flush();
  assert.match(h.get('wbStatus').textContent,/erreur/);
  assert.equal(JSON.stringify(h.context.EduBacBoard.getObjects()),before);
});
test('read-only tutor can send selected content but response-to-board stays disabled',async()=>{
  const h=harness({edit:false,tutor:true});await flush();
  h.get('wbCanvas').emit('mousedown',{clientX:920,clientY:110});
  h.answers.push({reply:'Observe le coefficient de x.',actions:[{action:'add_note',content:'Indice'}],can_edit:false});
  h.intents[1].click();await flush();
  const request=JSON.parse(h.requests.at(-1).options.body);
  assert.equal(request.intent,'hint');assert.equal(request.selected_id,h.context.EduBacBoard.getSelected().id);
  assert.equal(h.get('wbTutorLog').children.at(-1).children.find(c=>c.tagName==='BUTTON').disabled,true);
});
test('large boards include the selected legacy object within the 250-object context cap',async()=>{
  const objects=Array.from({length:280},(_,i)=>({type:'text',text:'Étape '+i,x:60,y:70+i*50,size:3}));
  const h=harness({objects,tutor:true});await flush();
  h.tools[0].click();h.get('wbCanvas').emit('mousedown',{clientX:70,clientY:4});
  // The DOM mock keeps a fixed viewport despite board extension. Select at the
  // first object's logical coordinate via the current canvas ratio.
  const ratio=h.get('wbCanvas').height/1000;
  h.get('wbCanvas').emit('mousedown',{clientX:70,clientY:65/ratio});h.get('wbCanvas').emit('mouseup');
  assert.ok(h.context.EduBacBoard.getSelected());
  h.get('wbTutorQuestion').value='Explique cette étape.';
  h.get('wbTutorForm').emit('submit');await flush();
  const request=JSON.parse(h.requests.at(-1).options.body);
  assert.equal(request.objects.length,250);
  assert.ok(request.objects.some(o=>o.id===request.selected_id));
});
test('tutor serialization strips image/runtime/unknown fields and downsamples strokes without altering saved originals',()=>{
  const points=Array.from({length:12000},(_,i)=>({x:i+.123456,y:Math.sin(i)*20,pressure:.5}));
  const original={id:'pen-1',type:'stroke',points,color:'#352443',size:4,_fn:()=>{},_width:800,src:'data:image/png;base64,HUGE',data:'HUGE',arbitraryRuntime:{secret:'no'}};
  const compact=model.tutorObject(original);
  assert.equal(compact.points.length,200);
  assert.equal(compact.points[0].x,.123);
  assert.equal(compact.points.at(-1).x,11999.123);
  assert.equal(compact.points.some(p=>'pressure' in p),false);
  ['_fn','_width','src','data','arbitraryRuntime'].forEach(k=>assert.equal(k in compact,false));
  assert.equal(original.points.length,12000);
  assert.equal(original.points[0].x,.123456);
  assert.equal(model.tutorObject({id:'img',type:'image',src:'data:image/png;base64,HUGE',x:30,y:40,w:200,h:100}).src,undefined);
});
test('complete UTF-8 request fits 2.4 MB with a near-limit image and large Unicode board; selection is retained',()=>{
  const objects=Array.from({length:250},(_,i)=>({id:'object-'+i,type:'text',text:'رياضيات'.repeat(580),x:i,y:i}));
  const image='data:image/png;base64,'+'a'.repeat(2*1024*1024-80);
  const payload=model.tutorPayload({question:'Explique.',mode:'hint',intent:'ask',selected_id:'object-0',objects,image,history:Array.from({length:12},(_,i)=>({role:i%2?'assistant':'user',content:'Étape '.repeat(700)})),previous_attempts:['x=4']});
  assert.ok(Buffer.byteLength(JSON.stringify(payload),'utf8')<2400000);
  assert.equal(model.bytes(JSON.stringify(payload)),Buffer.byteLength(JSON.stringify(payload),'utf8'));
  assert.ok(payload.objects.length<=250);
  assert.ok(payload.objects.some(o=>o.id==='object-0'));
  assert.equal(payload.image,image);
  assert.equal(objects[0].text.length,'رياضيات'.repeat(580).length);
  assert.throws(()=>model.tutorPayload({objects:[],image:'a'.repeat(2*1024*1024)}),/moins de 2 Mo/);
  assert.equal(model.bytes('é数学𐐀'),Buffer.byteLength('é数学𐐀'));
});
test('ruler and protractor create editable movable geometry using existing line/circle schema and persist',async()=>{
  const h=harness({objects:[]});await flush();
  h.tools.find(t=>t.dataset.tool==='ruler').click();
  h.get('wbCanvas').emit('mousedown',{clientX:100,clientY:200});
  h.get('wbCanvas').emit('mousemove',{clientX:400,clientY:200});
  h.get('wbCanvas').emit('mouseup',{clientX:400,clientY:200});
  const ruler=h.context.EduBacBoard.getObjects()[0];
  assert.equal(ruler.type,'line');assert.equal(ruler.geometry,'ruler');
  h.tools.find(t=>t.dataset.tool==='protractor').click();
  h.get('wbCanvas').emit('mousedown',{clientX:700,clientY:350});
  h.get('wbCanvas').emit('mousemove',{clientX:850,clientY:350});
  h.get('wbCanvas').emit('mouseup',{clientX:850,clientY:350});
  const protractor=h.context.EduBacBoard.getObjects()[1];
  assert.equal(protractor.type,'circle');assert.equal(protractor.geometry,'protractor');assert.equal(protractor.angle,60);
  assert.equal(model.hit(protractor,{x:700,y:300}),true);
  assert.equal(model.hit(protractor,{x:700,y:430}),false,'lower half is outside the semicircular instrument');
  h.tools[0].click();
  h.get('wbCanvas').emit('mousedown',{clientX:700,clientY:300});h.get('wbCanvas').emit('mouseup');
  h.get('wbEditSelected').click();
  const angle=h.get('wbEditorFields').children.flatMap(c=>c.children).find(input=>input.name==='angle');
  angle.value='75';h.get('wbEditorForm').emit('submit');
  assert.equal(h.context.EduBacBoard.getSelected().angle,75);
  h.get('wbCanvas').emit('mousedown',{clientX:700,clientY:300});
  h.get('wbCanvas').emit('mousemove',{clientX:720,clientY:320});h.get('wbCanvas').emit('mouseup');
  assert.equal(h.context.EduBacBoard.getSelected().cx,720);
  h.get('wbSaveBtn').click();await flush();
  assert.equal(h.saved()[1].geometry,'protractor');assert.equal(h.saved()[1].angle,75);
  h.get('wbDeleteSelected').click();assert.equal(h.context.EduBacBoard.getObjects().length,1);
  h.get('wbUndo').click();assert.equal(h.context.EduBacBoard.getObjects().length,2);
});
test('readonly guards apply even to synthetic placement/image/editor/clear events and geometry tools',async()=>{
  const h=harness({edit:false,objects:[]});await flush();
  h.get('wbMathInput').value='x=4';h.get('wbMathPlace').click();
  h.get('wbGraphFn').value='x*x';h.get('wbGraphPlace').click();
  h.get('wbImageInput').files=[{name:'test.png'}];h.get('wbImageInput').emit('change');
  h.get('wbEditorForm').emit('submit');h.get('wbClear').click();
  for(const tool of ['ruler','protractor','text','pencil']) {
    h.tools.find(t=>t.dataset.tool===tool).click();
    h.get('wbCanvas').emit('mousedown',{clientX:30,clientY:30});
    h.get('wbCanvas').emit('mousemove',{clientX:80,clientY:80});
    h.get('wbCanvas').emit('mouseup',{clientX:80,clientY:80});
  }
  h.get('wbSaveBtn').click();await flush();
  assert.equal(h.context.EduBacBoard.getObjects().length,0);
  assert.equal(h.requests.some(r=>r.options?.method==='POST'),false);
});
test('markdown image syntax and HTML in assistant replies remain literal text, not browser elements',async()=>{
  const h=harness({tutor:true});await flush();
  h.answers.push({reply:'![diagram](javascript:alert(1)) <img src=x onerror=alert(1)>',actions:[],can_edit:true});
  h.get('wbTutorQuestion').value='Explique.';h.get('wbTutorForm').emit('submit');await flush();
  const article=h.get('wbTutorLog').children.at(-1);
  assert.match(textOf(article),/!\[diagram\]\(javascript:alert\(1\)\)/);
  function descendants(node){return (node.children || []).flatMap(c=>[c,...descendants(c)]);}
  assert.equal(descendants(article).some(c=>['IMG','SCRIPT','IFRAME'].includes(c.tagName)),false);
});

test('local smoothing keeps endpoints, corners, loops and bounded deviations without mutating raw points',()=>{
  const raw=[{x:0,y:0},{x:10,y:1},{x:20,y:-1},{x:30,y:0}];
  const before=JSON.stringify(raw), smoothed=model.smoothPoints(raw);
  assert.equal(JSON.stringify(raw),before);
  assert.deepEqual(smoothed[0],raw[0]);assert.deepEqual(smoothed.at(-1),raw.at(-1));
  assert.equal(smoothed.length,6);
  for(let i=1;i<raw.length-1;i++){
    for(const p of smoothed.slice(2*i-1,2*i+1))assert.ok(Math.hypot(p.x-raw[i].x,p.y-raw[i].y)<=2.000001);
  }
  const corner=[{x:0,y:0},{x:30,y:0},{x:30,y:40}];
  assert.deepEqual(model.smoothPoints(corner),corner,'right angles remain exact');
  const loop=[{x:0,y:0},{x:15,y:20},{x:30,y:0},{x:0,y:0}];
  assert.deepEqual(model.smoothPoints(loop)[0],model.smoothPoints(loop).at(-1));
  assert.deepEqual(model.smoothPoints([{x:8,y:9}]),[{x:8,y:9}]);
  assert.deepEqual(model.smoothPoints([{x:0,y:0},{x:0,y:0},{x:4,y:4}]),[{x:0,y:0},{x:0,y:0},{x:4,y:4}]);
});

test('pointer capture collects coalesced samples, ignores other pointers, finishes outside and saves the rendered points',async()=>{
  const h=harness({objects:[],pointer:true});await flush();
  const canvas=h.get('wbCanvas');
  canvas.emit('pointerdown',{pointerId:1,button:2,clientX:10,clientY:10});
  assert.equal(canvas.captured,undefined);
  canvas.emit('pointerdown',{pointerId:1,button:0,clientX:10,clientY:10});
  assert.equal(canvas.captured,1);
  canvas.emit('pointerdown',{pointerId:2,button:0,clientX:600,clientY:600});
  h.emit('pointermove',{pointerId:2,clientX:600,clientY:600});
  h.emit('pointermove',{pointerId:1,clientX:40,clientY:11,getCoalescedEvents:()=>[
    {clientX:20,clientY:11},{clientX:30,clientY:9},{clientX:40,clientY:11}
  ]});
  h.emit('pointerup',{pointerId:1,clientX:1650,clientY:14});
  h.emit('pointerup',{pointerId:1,clientX:1700,clientY:14});
  const objects=h.context.EduBacBoard.getObjects();
  assert.equal(objects.length,1);
  assert.equal(objects[0].points[0].x,10);
  assert.equal(objects[0].points.at(-1).x,1650,'outside release is retained');
  assert.equal(objects[0].points.length,8,'coalesced samples retained and smoothed once');
  assert.equal(canvas.captured,null);
  h.get('wbSaveBtn').click();await flush();
  const saved=h.saved()[0];
  assert.deepEqual(saved.points,JSON.parse(JSON.stringify(objects[0].points)));
  const restored=harness({objects:h.saved()});await flush();
  assert.deepEqual(JSON.parse(JSON.stringify(restored.context.EduBacBoard.getObjects()[0].points)),saved.points);
  assert.ok(restored.strokes.some(points=>JSON.stringify(points)===JSON.stringify(saved.points)));
  h.get('wbUndo').click();assert.equal(h.context.EduBacBoard.getObjects().length,0);
  h.get('wbRedo').click();assert.equal(h.context.EduBacBoard.getObjects()[0].points.at(-1).x,1650);
});

test('pointer cancellation, capture loss and blur finish once at the last valid sample; taps persist',async()=>{
  for(const end of ['pointercancel','lostpointercapture','blur']){
    const h=harness({objects:[],pointer:true});await flush();
    h.get('wbCanvas').emit('pointerdown',{pointerId:4,button:0,clientX:45,clientY:60});
    h.emit('pointermove',{pointerId:4,clientX:50,clientY:62});
    if(end==='lostpointercapture')h.get('wbCanvas').emit(end,{pointerId:4});
    else h.emit(end,{pointerId:4,clientX:0,clientY:0});
    h.emit('pointerup',{pointerId:4,clientX:0,clientY:0});
    const objects=h.context.EduBacBoard.getObjects();
    assert.equal(objects.length,1,end);
    assert.equal(objects[0].points.at(-1).x,50,end);
  }
  const h=harness({objects:[],pointer:true});await flush();
  h.get('wbCanvas').emit('pointerdown',{pointerId:1,button:0,clientX:45,clientY:60});
  h.emit('pointerup',{pointerId:1,clientX:45,clientY:60});
  assert.equal(h.context.EduBacBoard.getObjects()[0].points.length,1);
});

test('text uses the existing dialog for creation, cancellation and Arabic multiline editing; moves are one undo step',async()=>{
  const h=harness({objects:[],pointer:true});await flush();
  h.tools.find(t=>t.dataset.tool==='text').click();
  h.get('wbCanvas').emit('pointerdown',{pointerId:1,button:0,clientX:200,clientY:150});
  assert.equal(h.get('wbObjectEditor').open,true);
  assert.equal(h.context.EduBacBoard.getObjects().length,0);
  h.get('wbEditorCancel').click();
  assert.equal(h.get('wbUndo').disabled,true,'cancel creates no history');
  h.get('wbCanvas').emit('pointerdown',{pointerId:2,button:0,clientX:200,clientY:150});
  const input=h.get('wbEditorFields').children.flatMap(c=>c.children).find(c=>c.name==='text');
  assert.equal(input.dir,'auto');assert.equal(input.focused,true);
  input.value=' ';h.get('wbEditorForm').emit('submit');
  assert.equal(h.get('wbObjectEditor').open,true);
  input.value='رياضيات\nx = 7';h.get('wbEditorForm').emit('submit');
  assert.equal(h.context.EduBacBoard.getSelected().text,'رياضيات\nx = 7');
  assert.equal(h.tools[0].attrs['aria-pressed'],'true');
  assert.equal(h.tools.find(t=>t.dataset.tool==='text').attrs['aria-pressed'],'false');
  assert.ok(h.drawnText.some(line=>line.text==='رياضيات'));
  assert.equal('_width' in h.context.EduBacBoard.getSelected(),false);
  h.get('wbCanvas').emit('pointerdown',{pointerId:3,button:0,clientX:210,clientY:140});
  h.emit('pointerup',{pointerId:3,clientX:250,clientY:160});
  assert.equal(h.context.EduBacBoard.getSelected().x,240,'release-only movement retained');
  h.get('wbUndo').click();assert.equal(h.context.EduBacBoard.getSelected().x,200);
  h.get('wbRedo').click();assert.equal(h.context.EduBacBoard.getSelected().x,240);
  h.emit('keydown',{key:'Enter',target:h.get('wbCanvas')});
  assert.equal(h.get('wbObjectEditor').open,true);
  const edit=h.get('wbEditorFields').children.flatMap(c=>c.children).find(c=>c.name==='text');
  edit.value='نص جديد';h.get('wbEditorForm').emit('submit');
  assert.equal(h.context.EduBacBoard.getObjects().length,1);
  h.get('wbUndo').click();assert.equal(h.context.EduBacBoard.getSelected().text,'رياضيات\nx = 7');
  h.get('wbSaveBtn').click();await flush();
  assert.equal(h.saved()[0].text,'رياضيات\nx = 7');
});

test('legacy mouse fallback can release outside and read-only/student pointer paths remain inert',async()=>{
  const h=harness({objects:[]});await flush();
  h.get('wbCanvas').emit('mousedown',{clientX:20,clientY:30});
  h.emit('mousemove',{clientX:90,clientY:70});
  h.emit('mouseup',{clientX:130,clientY:95});
  assert.equal(h.context.EduBacBoard.getObjects()[0].points.at(-1).x,130);
  for(const options of [{edit:false},{edit:true,student:true}]){
    const locked=harness({...options,pointer:true});await flush();
    const before=JSON.stringify(locked.context.EduBacBoard.getObjects());
    locked.get('wbCanvas').emit('pointerdown',{pointerId:1,button:0,clientX:620,clientY:120});
    locked.emit('pointermove',{pointerId:1,clientX:650,clientY:160});
    locked.emit('pointerup',{pointerId:1,clientX:650,clientY:160});
    assert.equal(JSON.stringify(locked.context.EduBacBoard.getObjects()),before);
  }
});

test('preview work is frame-batched without dropping input; pending frames cannot redraw after release',async()=>{
  const h=harness({objects:[],pointer:true});await flush();
  const frames=new Map();let next=0;
  h.context.requestAnimationFrame=fn=>{frames.set(++next,fn);return next;};
  h.context.cancelAnimationFrame=id=>frames.delete(id);
  h.get('wbCanvas').emit('pointerdown',{pointerId:1,button:0,clientX:10,clientY:10});
  for(let i=1;i<=4;i++)h.emit('pointermove',{pointerId:1,clientX:10+i*10,clientY:10+i});
  assert.equal(frames.size,1);
  const raw=Array.from({length:5},(_,i)=>({x:10+i*10,y:10+i}));
  h.emit('pointerup',{pointerId:1,clientX:50,clientY:14});
  assert.equal(frames.size,0);
  assert.deepEqual(JSON.parse(JSON.stringify(h.context.EduBacBoard.getObjects()[0].points)),model.smoothPoints(raw));
});

test('legacy strokes remain unchanged and pointer shape endpoints honor canvas scaling',async()=>{
  const original={type:'stroke',points:[{x:10,y:10},{x:20,y:11},{x:30,y:9}],size:4,color:'#352443'};
  const h=harness({objects:[original],pointer:true});await flush();
  h.get('wbSaveBtn').click();await flush();
  assert.deepEqual(h.saved()[0].points,original.points,'saved boards are not re-smoothed');
  h.get('wbCanvas').getBoundingClientRect=()=>({left:100,top:40,width:800,height:500});
  h.tools.find(t=>t.dataset.tool==='line').click();
  h.get('wbCanvas').emit('pointerdown',{pointerId:1,button:0,clientX:150,clientY:90});
  h.emit('pointerup',{pointerId:1,clientX:1000,clientY:140});
  const line=h.context.EduBacBoard.getObjects()[1];
  assert.equal(line.x1,100);assert.equal(line.y1,100);
  assert.equal(line.x2,1800);assert.equal(line.y2,200);
});
