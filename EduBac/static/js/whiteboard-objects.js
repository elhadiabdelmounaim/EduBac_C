/* Shared, DOM-independent object operations. Persist the existing v1 schema. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EduBacObjects = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  function serialize(o) {
    var copy = {};
    Object.keys(o).forEach(function (key) { if (key.charAt(0) !== '_') copy[key] = o[key]; });
    return copy;
  }
  function state(objects) { return JSON.stringify(objects.map(serialize)); }
  // One bounded corner-cutting pass. Endpoints and deliberate sharp corners
  // stay put. Persist the resulting ordinary v1 points, never re-smooth on load.
  function smoothPoints(points) {
    if (points.length < 3) return points.map(function(p){return {x:p.x,y:p.y};});
    var result=[{x:points[0].x,y:points[0].y}];
    for(var i=1;i<points.length-1;i++) {
      var a=points[i-1], b=points[i], c=points[i+1];
      var incoming=Math.hypot(b.x-a.x,b.y-a.y), outgoing=Math.hypot(c.x-b.x,c.y-b.y);
      var cosine=incoming && outgoing ? ((b.x-a.x)*(c.x-b.x)+(b.y-a.y)*(c.y-b.y))/(incoming*outgoing) : -1;
      if(cosine<.35) {result.push({x:b.x,y:b.y});continue;}
      var trim=Math.min(2,incoming*.2,outgoing*.2);
      result.push({x:b.x+(a.x-b.x)*trim/incoming,y:b.y+(a.y-b.y)*trim/incoming});
      result.push({x:b.x+(c.x-b.x)*trim/outgoing,y:b.y+(c.y-b.y)*trim/outgoing});
    }
    var last=points[points.length-1];
    result.push({x:last.x,y:last.y});
    return result;
  }
  function tutorObject(o) {
    // Tutor transport is deliberately distinct from persistence: images travel
    // separately, and drawing samples must not exhaust Django's request limit.
    var result={};
    ['id','type','text','latex','expr','color','geometry'].forEach(function(k){
      if(typeof o[k]==='string')result[k]=o[k].slice(0,['id','type','color','geometry'].includes(k)?160:4000);
    });
    ['x','y','x1','y1','x2','y2','x3','y3','cx','cy','w','h','r','size','alpha','xmin','xmax','ymin','ymax','angle'].forEach(function(k){
      if(typeof o[k]==='number' && Number.isFinite(o[k]))result[k]=Math.round(Math.max(-1e7,Math.min(1e7,o[k]))*1000)/1000;
    });
    ['erase','note'].forEach(function(k){if(typeof o[k]==='boolean')result[k]=o[k];});
    if(Array.isArray(o.points)) {
      var points=o.points.filter(function(p){return p && Number.isFinite(p.x) && Number.isFinite(p.y);});
      var count=Math.min(200,points.length);
      result.points=[];
      for(var i=0;i<count;i++){
        var p=points[count===1?0:Math.round(i*(points.length-1)/(count-1))];
        result.points.push({x:Math.round(Math.max(-1e7,Math.min(1e7,p.x))*1000)/1000,y:Math.round(Math.max(-1e7,Math.min(1e7,p.y))*1000)/1000});
      }
    }
    return result;
  }
  function bytes(text) {
    var total=0;
    for(var i=0;i<text.length;i++){
      var c=text.charCodeAt(i);
      if(c<128)total++;
      else if(c<2048)total+=2;
      else if(c>=0xd800 && c<=0xdbff && i+1<text.length && text.charCodeAt(i+1)>=0xdc00 && text.charCodeAt(i+1)<=0xdfff){total+=4;i++;}
      else total+=3;
    }
    return total;
  }
  function tutorPayload(payload) {
    var result=Object.assign({},payload);
    var all=payload.objects || [], selected=all.find(function(o){return o.id===payload.selected_id;});
    result.objects=all.slice(-250).map(tutorObject);
    if(selected && !result.objects.some(function(o){return o.id===selected.id;}))result.objects[0]=tutorObject(selected);
    result.history=(payload.history || []).slice(-12).map(function(item){return {role:item.role,content:String(item.content || '').slice(0,4000)};});
    result.previous_attempts=(payload.previous_attempts || []).slice(-10).map(function(item){return String(item).slice(0,4000);});
    if(result.image && bytes(result.image)>=2*1024*1024)throw new Error('L’image doit faire moins de 2 Mo. Joins une version plus petite.');
    // 2.4 MB decimal leaves a margin below Django's 2.5 MiB default.
    var length=bytes(JSON.stringify(result));
    while(length>=2400000) {
      var index=result.objects.findIndex(function(o){return o.id!==result.selected_id;});
      if(index>=0){length-=bytes(JSON.stringify(result.objects[index]))+(result.objects.length>1?1:0);result.objects.splice(index,1);continue;}
      if(result.history.length){length-=bytes(JSON.stringify(result.history[0]))+(result.history.length>1?1:0);result.history.shift();continue;}
      if(result.previous_attempts.length){length-=bytes(JSON.stringify(result.previous_attempts[0]))+(result.previous_attempts.length>1?1:0);result.previous_attempts.shift();continue;}
      throw new Error('Le contexte est trop volumineux. Réduis l’image ou l’énoncé.');
    }
    return result;
  }
  function id() { return 'wb-' + (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)); }
  function normalize(objects) {
    var seen = new Set();
    return objects.map(function (o, index) {
      if (!o.id || seen.has(o.id)) {
        var str = JSON.stringify(serialize(o)), hash = 2166136261;
        for (var i = 0; i < str.length; i++) hash = Math.imul(hash ^ str.charCodeAt(i), 16777619);
        o.id = 'legacy-' + (hash >>> 0).toString(36) + '-' + index;
      }
      seen.add(o.id);
      return o;
    });
  }
  function bounds(o) {
    if (o.type === 'stroke') {
      var pts = o.points || [];
      if (!pts.length) return { x:0, y:0, w:0, h:0 };
      var extent=pts.reduce(function(b,p){b.minX=Math.min(b.minX,p.x);b.minY=Math.min(b.minY,p.y);b.maxX=Math.max(b.maxX,p.x);b.maxY=Math.max(b.maxY,p.y);return b;},{minX:Infinity,minY:Infinity,maxX:-Infinity,maxY:-Infinity});
      return {x:extent.minX,y:extent.minY,w:extent.maxX-extent.minX,h:extent.maxY-extent.minY};
    }
    if(o.type==='circle' && o.geometry==='protractor')return {x:o.cx-o.r,y:o.cy-o.r,w:o.r*2,h:o.r+20};
    if (o.type === 'circle') return { x:o.cx-o.r, y:o.cy-o.r, w:o.r*2, h:o.r*2 };
    if (o.x1 != null) {
      var xx = [o.x1, o.x2], yy = [o.y1, o.y2];
      if (o.x3 != null) { xx.push(o.x3); yy.push(o.y3); }
      var box={ x:Math.min.apply(null, xx), y:Math.min.apply(null, yy), w:Math.max.apply(null, xx)-Math.min.apply(null, xx), h:Math.max.apply(null, yy)-Math.min.apply(null, yy) };
      if(o.geometry==='ruler'){box.x-=30;box.y-=30;box.w+=60;box.h+=60;}
      return box;
    }
    if (o.type === 'text' || o.type === 'note') {
      var font = (o.size || 4)*4+12, lines = String(o.text || '').split('\n');
      return { x:o.x, y:o.y-font, w:o._width != null ? o._width : (o.w || Math.max.apply(null, lines.map(function (s) { return s.length*font*.62; }))), h:o._height || lines.length*font*1.3+8 };
    }
    return { x:o.x || 0, y:o.y || 0, w:o._width || o.w || Math.max(80, String(o.latex || '').length*16), h:o._height || o.h || 40 };
  }
  function distance(p, a, b) {
    var dx=b.x-a.x, dy=b.y-a.y, len=dx*dx+dy*dy;
    var t=len ? Math.max(0, Math.min(1, ((p.x-a.x)*dx+(p.y-a.y)*dy)/len)) : 0;
    return Math.hypot(p.x-a.x-t*dx, p.y-a.y-t*dy);
  }
  function hit(o, p, tolerance) {
    var t = tolerance || 9;
    if (o.type === 'stroke') {
      var pts=o.points || [];
      if (pts.length === 1) return distance(p, pts[0], pts[0]) <= t+(o.size || 1)/2;
      return pts.some(function (pt, i) { return i && distance(p, pts[i-1], pt) <= t+(o.size || 1)/2; });
    }
    if (o.type === 'line' || o.type === 'arrow') return distance(p, {x:o.x1,y:o.y1}, {x:o.x2,y:o.y2}) <= (o.geometry==='ruler'?30:t)+(o.size || 1);
    if (o.type === 'circle') return Math.hypot(p.x-o.cx,p.y-o.cy) <= o.r+t && (o.geometry!=='protractor' || p.y<=o.cy+t);
    if (o.type === 'triangle') {
      var a={x:o.x1,y:o.y1}, b={x:o.x2,y:o.y2}, c={x:o.x3,y:o.y3};
      function cross(u,v) { return (p.x-v.x)*(u.y-v.y)-(u.x-v.x)*(p.y-v.y); }
      var d=[cross(a,b),cross(b,c),cross(c,a)];
      return !(d.some(function(v){return v<0;}) && d.some(function(v){return v>0;})) || distance(p,a,b)<=t || distance(p,b,c)<=t || distance(p,c,a)<=t;
    }
    var box=bounds(o);
    return p.x>=box.x-t && p.x<=box.x+box.w+t && p.y>=box.y-t && p.y<=box.y+box.h+t;
  }
  function move(o, dx, dy) {
    ['x','x1','x2','x3','cx'].forEach(function(k){ if(typeof o[k]==='number') o[k]+=dx; });
    ['y','y1','y2','y3','cy'].forEach(function(k){ if(typeof o[k]==='number') o[k]+=dy; });
    if(o.points) o.points=o.points.map(function(p){return {x:p.x+dx,y:p.y+dy};});
    return o;
  }
  function overlap(a,b) { return a.x < b.x+b.w+24 && a.x+a.w+24 > b.x && a.y < b.y+b.h+24 && a.y+a.h+24 > b.y; }
  function actions(actions, objects, width) {
    var result=[], placed=objects.map(bounds), maxWidth=Math.max(240, (width || 1600)-80);
    (Array.isArray(actions) ? actions : []).slice(0,30).forEach(function(a) {
      if (!a || !['add_text','add_equation','add_note'].includes(a.action) || typeof a.content !== 'string' || !a.content.trim()) return;
      var content=a.content.slice(0,4000), obj={id:id(), type:a.action==='add_equation'?'math':'text', x:40,y:60,color:'#352443',size:3};
      if(a.action==='add_note') obj.note=true;
      if(obj.type==='math') { obj.latex=content; obj.w=Math.min(maxWidth,Math.max(240,content.length*18)); obj.h=60; }
      else {
        var lines=[];
        content.split('\n').forEach(function(line){
          var limit=Math.max(16,Math.floor(Math.min(600,maxWidth)/15));
          while(line.length>limit) { var cut=line.lastIndexOf(' ',limit); if(cut<1)cut=limit; lines.push(line.slice(0,cut)); line=line.slice(cut).trimStart(); }
          lines.push(line);
        });
        obj.text=lines.join('\n'); obj.w=Math.min(600,maxWidth);
      }
      var box=bounds(obj), attempts=0;
      while(placed.some(function(b){return overlap(box,b);}) && attempts++<10000) { obj.y+=40; box=bounds(obj); }
      placed.push(box); result.push(obj);
    });
    return result;
  }
   return { serialize:serialize, state:state, id:id, normalize:normalize, bounds:bounds, hit:hit, move:move, actions:actions, tutorObject:tutorObject, tutorPayload:tutorPayload, bytes:bytes, smoothPoints:smoothPoints };
});
