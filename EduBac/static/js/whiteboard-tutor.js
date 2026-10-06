/* Tutor transport + compact French study panel. No provider credentials here. */
(function () {
  'use strict';
  var app=document.getElementById('wbApp'), board=window.EduBacBoard;
  if(!app || !board) return;
  function el(id){return document.getElementById(id);}
  var panel=el('wbTutor'), log=el('wbTutorLog'), question=el('wbTutorQuestion');
  var mode='hint', history=[], attempts=[], image=null, busy=false, lastRequest=null;
  var prompts={explain:'Explique cette étape sans sauter à la réponse finale.',hint:'Donne-moi un indice pour cette étape.',verify:'Vérifie ma réponse et indique la première étape à revoir.',solve:'Résous cet exercice étape par étape.',rule:'Quelle règle mathématique utilise-t-on ici ?'};
  function open(value) {
    panel.hidden=!value;el('wbTutorToggle').setAttribute('aria-expanded',String(value));
    context();
    window.dispatchEvent(new Event('resize'));
  }
  el('wbTutorToggle').addEventListener('click',function(){open(panel.hidden);if(!panel.hidden)question.focus();});
  el('wbTutorClose').addEventListener('click',function(){open(false);el('wbTutorToggle').focus();});
  function choose(value) {
    mode=value;
    document.querySelectorAll('[data-mode]').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.mode===mode));});
  }
  document.querySelectorAll('[data-mode]').forEach(function(b){b.addEventListener('click',function(){choose(b.dataset.mode);});});
  function context() {
    var o=board.getSelected(), count=board.getObjects().length;
    el('wbTutorSelection').textContent=(o ? 'Sélection : '+String(o.latex || o.text || o.expr || o.type).slice(0,160) : 'Contexte : tout le tableau')+' · '+count+' élément'+(count>1?'s':'')+(o && o.type==='image' ? ' · image sélectionnée envoyée' : ' · capture uniquement sur accord');
  }
  window.addEventListener('edubac:selection',context);
  function error(message,retry) {
    el('wbTutorError').hidden=false;el('wbTutorErrorText').textContent=message;
    el('wbTutorRetry').hidden=!retry;
  }
  function attachment(src,label) {
    if(typeof src!=='string' || !/^data:image\/(png|jpeg|webp);base64,/i.test(src)) throw new Error('Utilise une image PNG, JPEG ou WebP.');
    if(src.length>=2*1024*1024) throw new Error('L’image doit faire moins de 2 Mo. Réduis sa taille.');
    image=src;el('wbTutorAttachment').hidden=false;el('wbTutorThumbnail').src=src;el('wbTutorImageLabel').textContent=label || 'Image jointe';
  }
  el('wbTutorAttach').addEventListener('click',function(){el('wbTutorFile').click();});
  el('wbTutorFile').addEventListener('change',function(e){
    var file=e.target.files[0];if(!file)return;
    if(!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>1500000) {error('Choisis un fichier PNG, JPEG ou WebP de moins de 1,5 Mo.',false);return;}
    var reader=new FileReader();
    reader.onload=function(){try{attachment(reader.result,file.name);el('wbTutorError').hidden=true;}catch(err){error(err.message,false);}};
    reader.onerror=function(){error('Impossible de lire cette image. Essaie un autre fichier.',false);};
    reader.readAsDataURL(file);e.target.value='';
  });
  el('wbTutorRemoveImage').addEventListener('click',function(){image=null;el('wbTutorAttachment').hidden=true;el('wbTutorThumbnail').removeAttribute('src');});
  el('wbTutorSnapshot').addEventListener('click',function(){
    if(!confirm('Envoyer une capture de tes dessins à l’assistant IA ? Les équations et les autres éléments sont déjà transmis comme objets.'))return;
    try{attachment(board.snapshot(),'Capture du tableau');el('wbTutorError').hidden=true;}
    catch(err){error(err.message || 'La capture est indisponible. Joins une image à la place.',false);}
  });
  function richText(node,text) {
    /* Parse only math delimiters. All non-math content is a text node, never HTML. */
    var re=/\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\]|\$\$([\s\S]*?)\$\$|\$([^$\n]+)\$/g, match, cursor=0;
    while((match=re.exec(text))) {
      node.appendChild(document.createTextNode(text.slice(cursor,match.index)));
      var span=document.createElement('span'), latex=match[1] || match[2] || match[3] || match[4];
      try{if(window.katex)window.katex.render(latex,span,{throwOnError:false,trust:false,maxExpand:1000,displayMode:!!(match[2]||match[3])});else span.textContent=match[0];}
      catch(e){span.textContent=match[0];}
      node.appendChild(span);cursor=re.lastIndex;
    }
    node.appendChild(document.createTextNode(text.slice(cursor)));
  }
  function message(role,text) {
    var welcome=el('wbTutorWelcome');if(welcome)welcome.remove();
    var article=document.createElement('article');article.className='wb-chat-message '+role;
    var label=document.createElement('small');label.textContent=role==='user'?'Toi':'Assistant EduBac';
    var body=document.createElement('div');body.className='wb-message-body';richText(body,text);
    article.appendChild(label);article.appendChild(body);log.appendChild(article);
    log.scrollTop=log.scrollHeight;return article;
  }
  function response(data) {
    var article=message('assistant',typeof data.reply==='string'?data.reply:'');
    var v=data.verification;
    if(v && typeof v==='object') {
      var box=document.createElement('div');box.className='wb-verification';
      var title=document.createElement('strong');title.textContent=v.correct===true?'Réponse correcte':v.correct===false?'Une étape à revoir':'Vérification à préciser';box.appendChild(title);
      [['error_step','Étape'],['reason','Pourquoi'],['review_step','À revoir'],['rule','Règle']].forEach(function(pair){
        if(typeof v[pair[0]]==='string' && v[pair[0]]) {var p=document.createElement('p');richText(p,pair[1]+' : '+v[pair[0]]);box.appendChild(p);}
      });article.appendChild(box);
    }
    if(data.warning) {var warning=document.createElement('p');warning.className='wb-tutor-notice';warning.textContent=String(data.warning);article.appendChild(warning);}
    var actions=Array.isArray(data.actions)?data.actions:[];
    actions=actions.filter(function(a){return a && ['add_text','add_equation','add_note'].includes(a.action) && typeof a.content==='string';}).map(function(a){return {action:a.action,content:a.content};});
    if(!actions.length && data.reply)actions=[{action:'add_note',content:data.reply}];
    if(actions.length) {
      var add=document.createElement('button');add.type='button';add.textContent='Ajouter au tableau';
      add.disabled=!board.canEdit || data.can_edit!==true;
      if(add.disabled)add.title='Ajout indisponible en lecture seule.';
      add.addEventListener('click',function(){
        if(data.can_edit!==true)return;
        var result=board.addActions(actions);
        if(result.length){add.disabled=true;add.textContent='Ajouté · modifiable sur le tableau';}
      });article.appendChild(add);
    }
    if(data.context) {
      var c=data.context;
      el('wbTutorLesson').textContent=[c.niveau,c.lesson,c.exercise].filter(function(s){return typeof s==='string' && s.trim();}).join(' · ') || 'Niveau et leçon : fournis par EduBac.';
    }
    log.scrollTop=log.scrollHeight;context();
  }
  function loading(value) {
    busy=value;el('wbTutorLoading').hidden=!value;el('wbTutorSend').disabled=value;
    el('wbTutorRetry').disabled=value;panel.setAttribute('aria-busy',String(value));
    document.querySelectorAll('[data-tutor-intent]').forEach(function(b){b.disabled=value;});
  }
  async function send(intent,retry) {
    if(busy)return;
    var payload, typed=question.value, selected=board.getSelected();
    try {
      if(retry && lastRequest) payload=lastRequest;
      else {
        var text=(typed.trim() || prompts[intent] || '').trim();
        if(!text){error('Écris ta question ou choisis une action sur la sélection.',false);question.focus();return;}
        var objects=board.getObjects();
        /* Keep selected object in a bounded context even on very large boards. */
        if(objects.length>250) {
          objects=objects.slice(-250);
          if(selected && !objects.some(function(o){return o.id===selected.id;}))objects[0]=selected;
        }
        payload={question:text.slice(0,4000),mode:mode,intent:intent || 'ask',objects:objects,selected_id:selected?selected.id:null,previous_attempts:attempts.slice(-10),history:history.slice(-12)};
        var exercise=el('wbTutorExercise').value.trim();if(exercise)payload.exercise=exercise.slice(0,4000);
        var attached=image;
        if(!attached && selected && selected.type==='image') {
          if(!/^data:image\/(png|jpeg|webp);base64,/i.test(selected.src || '')) throw new Error('Cette image n’est pas intégrée au tableau. Joins son fichier pour l’envoyer.');
          attached=selected.src;
        }
        if(attached) {
          if(attached.length>=2*1024*1024)throw new Error('L’image doit faire moins de 2 Mo. Joins une version plus petite.');
          payload.image=attached;
        }
        payload=window.EduBacObjects.tutorPayload(payload);
        if(board.getObjects().length>payload.objects.length)message('assistant','Le tableau est grand : '+payload.objects.length+' éléments récents, dont ta sélection, sont envoyés. Les dessins sont transmis sous forme de points simplifiés.');
        message('user',payload.question);
        lastRequest=payload;
      }
    } catch(err){error(err.message,false);return;}
    el('wbTutorError').hidden=true;loading(true);
    var controller=new AbortController(), timeout=setTimeout(function(){controller.abort();},90000);
    try {
      var res=await fetch(app.dataset.tutorUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json','X-CSRFToken':app.dataset.csrf},body:JSON.stringify(payload),signal:controller.signal});
      var data;
      try{data=await res.json();}catch(e){throw new Error('L’assistant est momentanément indisponible.');}
      if(!res.ok)throw new Error(data.error || (res.status===429?'Trop de demandes. Patiente un instant avant de réessayer.':'La demande n’a pas abouti.'));
      if(typeof data.reply!=='string')throw new Error('La réponse reçue est incomplète. Réessaie.');
      response(data);
      history.push({role:'user',content:payload.question},{role:'assistant',content:data.reply.slice(0,4000)});
      history=history.slice(-12);
      if(payload.intent==='verify') {
        var attempt=payload.objects.find(function(o){return o.id===payload.selected_id;});
        if(attempt)attempts.push(String(attempt.latex || attempt.text || attempt.expr || '').slice(0,4000));
        attempts=attempts.slice(-10);
      }
      /* Never erase text or attachments changed while the request was in flight. */
      if(question.value===typed && !retry)question.value='';
      lastRequest=null;
    } catch(err){error(err.name==='AbortError'?'La réponse prend trop de temps. Ta question est conservée.':err.message,true);}
    finally{clearTimeout(timeout);loading(false);}
  }
  el('wbTutorForm').addEventListener('submit',function(e){e.preventDefault();send('ask',false);});
  el('wbTutorRetry').addEventListener('click',function(){send('ask',true);});
  document.querySelectorAll('[data-tutor-intent]').forEach(function(b){
    b.addEventListener('click',function(){
      if(!board.getSelected())return;
      open(true);var intent=b.dataset.tutorIntent;
      if(intent==='hint')choose('hint');
      if(intent==='explain' || intent==='rule' || intent==='verify')choose('explanation');
      if(intent==='solve')choose('solution');
      send(intent,false);
    });
  });
  context();
})();
