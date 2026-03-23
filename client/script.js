const API = "http://localhost:8000";
const WAKE_WORDS = ["shakti","शक्ति","શક્તિ","shakthi","sakti","shakty","shackti","shakathi","शक्‍ति","shakei"];

// STOP — English + Hindi Romanized (Whisper outputs Roman script)
const STOP_WORDS = [
  "stop","thank you","thanks","that's all","that will be all",
  "shukriya","dhanyavaad","dhanyawad","shukriyaa",
  "bas karo","bas","rukho","band karo",
  "aabhar","paur","thai gyu"   // Gujarati Romanized
];

// NEXT — English + Hindi Romanized + Gujarati Romanized
// "agla step", "agla kadam", "agle step" are the most common Hindi forms
const NEXT_WORDS = [
  "next","next step","continue","go ahead","proceed",
  "agla","aagla","agla step","agle step","agla kadam","agle","agli",
  "aage","aage badho","aage chalo",
  "aavu","agal","aagal","aglu"   // Gujarati Romanized
];

// REPEAT — English + Hindi Romanized + Gujarati Romanized
const RPT_WORDS = [
  "repeat","again","say again","once more","one more time",
  "dobara","dobara bolo","phir se","phir","phirse","wapas bolo",
  "fari","fari bolo","vari","vari kaho"   // Gujarati Romanized
];

// RESET — checked separately with regex, adding common Hindi forms here
const RESET_WORDS = [
  "reset","start over","restart","from beginning","start again",
  "shuru se","phir se shuru","naya shuru","wapas shuru",
  "pachhu jao","pachhi jao","nayi shuruat"
];

const S = {
  sessionId:null, totalSteps:0, currentStep:0, lastStepText:"",
  voiceOut:true, micState:"idle", lang:"en",
  micStream:null, mediaRecorder:null, audioChunks:[],
  vadInterval:null, vadTimer:null, audioCtx:null, ttsVoice:null,
  wakeRecog:null, sideStepCount:0,
};

// Clock
function p2(n){return String(n).padStart(2,'0');}
function nowTs(){const n=new Date();return p2(n.getHours())+':'+p2(n.getMinutes());}
setInterval(()=>{const n=new Date();document.getElementById('clock').textContent=p2(n.getHours())+':'+p2(n.getMinutes())+':'+p2(n.getSeconds());},1000);
const _n=new Date();document.getElementById('initTime').textContent=p2(_n.getHours())+':'+p2(_n.getMinutes());

function setStatus(s){document.getElementById('statusPill').className='status-pill '+s;document.getElementById('statusText').textContent=s.toUpperCase();}
function esc(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function scrollChat(){const c=document.getElementById('chatMessages');setTimeout(()=>c.scrollTop=c.scrollHeight,50);}

// TTS voices
// ── Browser TTS (speechSynthesis) ────────────────────────────────────────────

function pickVoice(){
  const vs = speechSynthesis.getVoices();
  if(!vs.length) return;
  const lang = S.lang;

  if(lang === 'hi'){
    S.ttsVoice = vs.find(v=>v.lang==='hi-IN') || vs.find(v=>v.lang.startsWith('hi')) || _pickEnglishVoice(vs);
    return;
  }
  if(lang === 'gu'){
    S.ttsVoice = vs.find(v=>v.lang==='gu-IN') || vs.find(v=>v.lang==='hi-IN') || _pickEnglishVoice(vs);
    return;
  }
  S.ttsVoice = _pickEnglishVoice(vs);
}

function _pickEnglishVoice(vs){
  return (
    vs.find(v => /zira/i.test(v.name))                                         ||  // Microsoft Zira (offline female)
    vs.find(v => v.localService && v.lang === 'en-IN')                         ||  // offline Indian English
    vs.find(v => /heera|neerja|ravi/i.test(v.name))                            ||  // Indian voices if installed
    vs.find(v => v.lang === 'en-IN')                                            ||  // any en-IN
    vs.find(v => v.localService && /female|woman|hazel|susan/i.test(v.name))   ||  // offline English female
    vs.find(v => v.localService && v.lang.startsWith('en'))                    ||  // any offline English
    vs.find(v => v.lang.startsWith('en'))                                       ||  // any English
    null
  );
}

speechSynthesis.onvoiceschanged = pickVoice;
pickVoice();
let _vp = setInterval(()=>{ if(S.ttsVoice){ clearInterval(_vp); } else { pickVoice(); } }, 200);

async function speakText(text, onDone){
  if(!S.voiceOut){ if(onDone) onDone(); return; }
  if(!text || !text.trim()){ if(onDone) onDone(); return; }

  speechSynthesis.cancel();
  if(!S.ttsVoice) pickVoice();

  const u   = new SpeechSynthesisUtterance(text);
  u.lang    = S.lang==='hi' ? 'hi-IN' : S.lang==='gu' ? 'gu-IN' : 'en-IN';
  u.rate    = 0.92;
  u.volume  = 1.0;
  if(S.ttsVoice) u.voice = S.ttsVoice;

  const sb  = document.getElementById('speakingBar');
  const btn = document.getElementById('voiceToggle');

  // Chrome stuck-speech watchdog
  const wd = setTimeout(()=>{ if(speechSynthesis.speaking){ speechSynthesis.pause(); speechSynthesis.resume(); }}, 500);

  u.onstart = ()=>{ sb.classList.add('active'); btn.classList.add('speaking'); setStatus('responding'); };
  u.onend   = ()=>{ clearTimeout(wd); sb.classList.remove('active'); btn.classList.remove('speaking'); setStatus('idle'); if(onDone) onDone(); };
  u.onerror = (e)=>{ clearTimeout(wd); sb.classList.remove('active'); btn.classList.remove('speaking'); setStatus('idle'); if(e.error!=='interrupted' && onDone) onDone(); };

  speechSynthesis.speak(u);
}


function toggleVoiceOut(){
  S.voiceOut=!S.voiceOut;
  const btn=document.getElementById('voiceToggle');
  document.getElementById('voiceIcon').textContent=S.voiceOut?'🔊':'🔇';
  document.getElementById('voiceLabel').textContent=S.voiceOut?'VOICE ON':'VOICE OFF';
  if(S.voiceOut){
    btn.classList.add('active');
    speakText('Shakti voice enabled.');
  } else {
    btn.classList.remove('active','speaking');
    speechSynthesis.cancel();
    document.getElementById('speakingBar').classList.remove('active');
    setStatus('idle');
  }
}

// AudioContext
function getAudioCtx(){
  if(!S.audioCtx)S.audioCtx=new(window.AudioContext||window.webkitAudioContext)();
  if(S.audioCtx.state==='suspended')S.audioCtx.resume();
  return S.audioCtx;
}

// Wake word listener
// ── WAKE WORD DETECTION — offline Whisper with sliding window ──────────────
// Records overlapping 1.5s clips continuously so "Shakti" can never fall
// in the gap between two clips. Two recorders alternate: while one is
// recording its 1.5s clip, the other starts 0.75s later — giving 0.75s
// of overlap. Any clip that contains "Shakti" triggers wake.

let _wakeActive = false;
let _wakeAborted = false;

function startWakeListener(){
  console.log("Wake listener disabled (no /transcribe)");
}

function stopWakeListener(){
  _wakeAborted = true;
  _wakeActive  = false;
  setWakeDot('');
}

// Each chain records a 1.5s clip, checks for wake word, then repeats.
// With two chains offset by 750ms, the effective check interval is 750ms.
async function _wakeChain(id){
  while(_wakeActive && S.micState === 'idle'){
    const clip = await _recordClip(1500);
    if(!_wakeActive || _wakeAborted) return;
    if(clip && clip.size > 500){
      _checkWakeClip(clip);   // fire-and-forget — don't await, keep recording
    }
    // Small pause to let the mic breathe between clips
    await new Promise(r => setTimeout(r, 50));
  }
}

async function _checkWakeClip(clip){
  if(!_wakeActive) return;
  try{
    const fd = new FormData();
    fd.append('audio', clip, 'wake.webm');
    fd.append('language', 'en');
    const r = await fetch(API+'/ask',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question, language: S.lang})
    })  
    if(!r.ok || !_wakeActive) return;
    const d = await r.json();
    const t = (d.transcript || '').toLowerCase().trim();
    if(t) console.log('[Wake] heard:', JSON.stringify(t));
    if(_wakeActive && WAKE_WORDS.some(w => t.includes(w))){
      stopWakeListener();
      onWakeDetected();
    }
  } catch(e){ /* server busy — clip discarded, next clip will try */ }
}

// Record a fixed-length audio clip from the persistent mic stream
function _recordClip(durationMs){
  return new Promise(resolve => {
    if(!S.micStream){ resolve(null); return; }
    const chunks = [];
    let rec;
    try{
      const _wm = ['audio/ogg;codecs=opus','audio/webm;codecs=opus','audio/webm','audio/mp4']
        .find(m => MediaRecorder.isTypeSupported(m)) || '';
      rec = new MediaRecorder(S.micStream, _wm ? {mimeType:_wm} : {});
    } catch(e){ resolve(null); return; }
    rec.ondataavailable = e => { if(e.data.size > 0) chunks.push(e.data); };
    rec.onstop = () => resolve(new Blob(chunks, {type:'audio/webm'}));
    rec.start();
    setTimeout(() => { if(rec.state !== 'inactive') rec.stop(); }, durationMs);
  });
}


function onWakeDetected(){
  console.log("Wake disabled");
}

function osc2(){
  try{
    const ctx=getAudioCtx(),osc=ctx.createOscillator(),g=ctx.createGain();
    osc.connect(g);g.connect(ctx.destination);
    osc.frequency.value=1100;g.gain.setValueAtTime(0.25,ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+0.1);
    osc.start(ctx.currentTime);osc.stop(ctx.currentTime+0.1);
  }catch(e){}
}
function setWakeDot(state){
  document.getElementById('wakeDot').className='wake-dot'+(state?' '+state:'');
  if(state==='rec')       document.getElementById('wakeLabel').textContent='RECORDING…';
  else if(state==='wake') document.getElementById('wakeLabel').textContent='LISTENING…';
  else                    document.getElementById('wakeLabel').textContent='SAY: SHAKTI';
}

// MIC BUTTON — press once to start, press again to stop & send
async function toggleMic(){
  if(S.micState==='idle'){getAudioCtx();await startMicRecording();}
  else if(S.micState==='recording'){stopMicRecording();}
}

async function startMicRecording(){
  // S.micStream is set at boot. If somehow null, acquire silently —
  // Chrome on localhost never re-prompts after the first grant.
  if(!S.micStream){
    try {
      S.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch(e) {
      addSysMsg('Microphone not available. Check browser permissions.');
      return;
    }
  }
  const stream = S.micStream;
  S.audioChunks=[];
  // Create a fresh MediaRecorder on the existing live stream
  // Pick the most compatible audio format for this browser/OS
  const _mime = ['audio/ogg;codecs=opus','audio/webm;codecs=opus','audio/webm','audio/mp4']
    .find(m => MediaRecorder.isTypeSupported(m)) || '';
  S.mediaRecorder=new MediaRecorder(S.micStream, _mime ? {mimeType:_mime} : {});
  S.mediaRecorder.ondataavailable=e=>{if(e.data.size>0)S.audioChunks.push(e.data);};
  S.mediaRecorder.onstop=()=>{stopVAD();clearTimeout(S.vadTimer);processAudio();};
  S.mediaRecorder.start(100);
  S.micState='recording';
  document.getElementById('micBtn').classList.add('rec');
  setWakeDot('rec');setStatus('listening');
  stopWakeListener();startVAD();
  S.vadTimer=setTimeout(()=>{if(S.micState==='recording')stopMicRecording();},30000);
}

function stopMicRecording(){
  if(S.mediaRecorder&&S.mediaRecorder.state!=='inactive')S.mediaRecorder.stop();
  S.micState='processing';
  document.getElementById('micBtn').classList.remove('rec');
  setWakeDot('');setStatus('processing');
}

// VAD
function startVAD(){
  stopVAD();
  const ctx=getAudioCtx(),src=ctx.createMediaStreamSource(S.micStream),an=ctx.createAnalyser();
  an.fftSize=512;src.connect(an);
  const buf=new Float32Array(an.fftSize);let silStart=null;
  const wrap=document.getElementById('vadWrap'),bar=document.getElementById('vadBar');
  wrap.classList.add('visible');bar.style.transform='scaleX(0)';
  S.vadInterval=setInterval(()=>{
    if(S.micState!=='recording'){stopVAD();return;}
    an.getFloatTimeDomainData(buf);
    let sum=0;for(let i=0;i<buf.length;i++)sum+=buf[i]*buf[i];
    const rms=Math.sqrt(sum/buf.length);
    const level=Math.min(1,rms/0.1);
    bar.style.transition='transform .1s linear';
    bar.style.transform='scaleX('+(0.05+level*0.95)+')';
    if(rms<0.015){if(!silStart)silStart=Date.now();if(Date.now()-silStart>=1800)stopMicRecording();}
    else silStart=null;
  },100);
}
function stopVAD(){
  clearInterval(S.vadInterval);S.vadInterval=null;
  document.getElementById('vadWrap').classList.remove('visible');
}

// Process audio -> Whisper -> RAG
async function processAudio(){
  // Voice disabled — fallback to text only
  addSysMsg('Voice input disabled. Please type your question.');
  resetMic();
}
function resetMic(){S.micState='idle';document.getElementById('micBtn').classList.remove('rec');setWakeDot('wake');}

// Text input
function sendTyped(){
  const inp=document.getElementById('textInput'),text=inp.value.trim();
  if(!text)return;inp.value='';
  sendQuestion(text);
}
function quickQuery(q){document.getElementById('textInput').value=q;sendTyped();}

// Send to RAG
async function sendQuestion(question, displayText){
  addOpMsg(displayText || question);setStatus('processing');addTyping();
  let data;
  try{
    const r=await fetch(API+'/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question, language: S.lang})});
    data=await r.json();
  }catch(e){removeTyping();addSysMsg('Cannot reach server. Is the backend running on port 8000?');setStatus('idle');return;}
  removeTyping();setStatus('responding');
  if(data.mode==='procedure'){
    S.sessionId=data.session_id;S.totalSteps=data.total_steps;
    S.currentStep=data.step.step_number;S.lastStepText=data.step.text;
    renderProcMsg(data);updateSidebar(data);updateDocs(data.sources);
    speakText('Step '+S.currentStep+' of '+S.totalSteps+'. '+S.lastStepText,()=>{setStatus('idle');reEnterConversation();});
  } else {
    S.sessionId=null;S.lastStepText=data.answer;
    renderInfoMsg(data);updateDocs(data.sources||[]);
    speakText(data.answer,()=>{setStatus('idle');reEnterConversation();});
  }
}

// Next / Repeat / Reset
async function nextStep(){
  if(!S.sessionId){addSysMsg('No active procedure.');return;}
  setStatus('processing');
  let data;
  try{const r=await fetch(API+'/next',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:S.sessionId})});data=await r.json();}
  catch(e){addSysMsg('Server error.');setStatus('idle');return;}
  if(data.step){
    S.currentStep=data.step.step_number;S.lastStepText=data.step.text;
    appendStep(data.step);
    speakText('Step '+S.currentStep+' of '+S.totalSteps+'. '+S.lastStepText,()=>{setStatus('idle');reEnterConversation();});
  } else {
    S.sessionId=null;addSysMsg('Procedure completed.');speakText('Procedure completed.',()=>{setStatus('idle');startWakeListener();});setProgress(100);
  }
}
function repeatStep(){if(!S.lastStepText){speakText('Nothing to repeat.',()=>reEnterConversation());return;}speakText(S.lastStepText,()=>reEnterConversation());}

// After Shakti speaks, stay in conversation mode so operator can say
// "next step", "repeat" etc without needing to say "Shakti" again.
// If operator is silent for VAD_SILENCE_MS, quietly return to wake mode.
function reEnterConversation(){
  // Disabled — no auto mic
}

function returnToWake(){
  // Called when we want to go back to passive wake-word listening
  if(S.micState !== 'idle') return;
  stopWakeListener();           // reset any existing listener
  setTimeout(startWakeListener, 200);
}
function resetProc(){
  S.sessionId=null;S.lastStepText='';S.totalSteps=0;S.currentStep=0;S.sideStepCount=0;
  document.getElementById('procedureName').innerHTML='<div class="pn-label">ACTIVE PROCEDURE</div>No procedure active';
  document.getElementById('procSteps').innerHTML='<div class="proc-step" style="padding:18px 14px"><span class="ps-label" style="color:var(--text-muted);font-style:italic;font-size:11px;">Procedure steps will appear here when a guided procedure is initiated.</span></div>';
  setProgress(0);addSysMsg('Procedure reset.');speakText('Procedure reset.',()=>reEnterConversation());
}
function markDone(){
  const cur=document.getElementById('cs_'+S.currentStep);
  if(cur){cur.classList.remove('current-step');cur.classList.add('done-step');}
  nextStep();
}

// Chat rendering
function addOpMsg(text){
  const c=document.getElementById('chatMessages'),el=document.createElement('div');
  el.className='msg-row operator';
  el.innerHTML='<div class="msg-avatar op">OPR</div><div class="msg-body"><div class="msg-meta">Operator &nbsp;·&nbsp; '+nowTs()+'</div><div class="msg-bubble op">'+esc(text)+'</div></div>';
  c.appendChild(el);scrollChat();
}
function addTyping(){
  const c=document.getElementById('chatMessages'),el=document.createElement('div');
  el.className='msg-row ai';el.id='typInd';
  el.innerHTML='<div class="msg-avatar ai">AI</div><div class="msg-body"><div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div>';
  c.appendChild(el);scrollChat();
}
function removeTyping(){const e=document.getElementById('typInd');if(e)e.remove();}
function addSysMsg(text){const c=document.getElementById('chatMessages'),el=document.createElement('div');el.className='sys-msg';el.textContent=text;c.appendChild(el);scrollChat();}

function pills(data){
  if(data.cache_hit) return '<span class="mpill cache">CACHE</span>';
  if(data.llm_used)  return '<span class="mpill llm">LLM</span>';
  return '<span class="mpill direct">DIRECT</span>';
}

function renderInfoMsg(data){
  const c=document.getElementById('chatMessages'),el=document.createElement('div');
  el.className='msg-row ai';
  const src=data.sources&&data.sources.length?'<div class="source-footnote"><span class="sf-label">SOURCE:</span> '+esc(data.sources[0].source)+' — Page '+data.sources[0].page+'</div>':'';
  el.innerHTML='<div class="msg-avatar ai">AI</div><div class="msg-body" style="max-width:82%"><div class="msg-meta">SHAKTI &nbsp;·&nbsp; '+nowTs()+' '+pills(data)+'</div><div class="msg-bubble ai">'+esc(data.answer)+src+'</div></div>';
  c.appendChild(el);scrollChat();
}

function renderProcMsg(data){
  const c=document.getElementById('chatMessages'),el=document.createElement('div');
  el.className='msg-row ai';
  const step=data.step;
  const src=data.sources&&data.sources.length?'<div class="source-footnote"><span class="sf-label">SOURCE:</span> '+esc(data.sources[0].source)+' — Page '+data.sources[0].page+'</div>':'';
  el.innerHTML='<div class="msg-avatar ai">AI</div><div class="msg-body" style="max-width:82%"><div class="msg-meta">SHAKTI &nbsp;·&nbsp; '+nowTs()+' &nbsp;·&nbsp; '+data.total_steps+' steps '+pills(data)+'</div>'
    +'<div class="msg-bubble ai">Procedure loaded — <strong>'+data.total_steps+' steps</strong> retrieved.'
    +'<div class="step-list" id="stepList">'
    +'<div class="step-item current-step" id="cs_'+step.step_number+'"><span class="step-num">'+p2(step.step_number)+'</span><div><span class="step-text">'+esc(step.text)+'</span></div></div>'
    +'</div>'
    +'<div class="guided-controls">'
    +'<button class="btn btn-primary" id="nextBtn" onclick="nextStep()">NEXT STEP →</button>'
    +'<button class="btn btn-outline" onclick="repeatStep()">↺ REPEAT</button>'
    +'<button class="btn btn-outline" onclick="resetProc()">✕ RESET</button>'
    +'</div>'+src+'</div></div>';
  c.appendChild(el);scrollChat();
}

function appendStep(step){
  const prev=document.getElementById('cs_'+(step.step_number-1));
  if(prev){prev.classList.remove('current-step');prev.classList.add('done-step');}
  const list=document.getElementById('stepList');
  if(list){
    const d=document.createElement('div');
    d.className='step-item current-step';d.id='cs_'+step.step_number;
    d.innerHTML='<span class="step-num">'+p2(step.step_number)+'</span><div><span class="step-text">'+esc(step.text)+'</span></div>';
    list.appendChild(d);
  }
  appendSidebarStep(step);
  scrollChat();
}

// Sidebar
function sidebarStepHTML(step, state){
  // state: 'current' | 'completed' | 'pending'
  const label = step.text.length>60 ? step.text.substring(0,57)+'…' : step.text;
  const icon  = state==='completed' ? '✔' : state==='current' ? '▶' : '';
  const badge = state==='completed' ? '<span class="ps-badge done">DONE</span>'
              : state==='current'   ? '<span class="ps-badge active">NOW</span>'
              : '';
  return '<div class="proc-step '+state+'" id="ss_'+step.step_number+'">'
    +'<span class="ps-num">'+p2(step.step_number)+'</span>'
    +'<div class="ps-icon">'+icon+'</div>'
    +'<span class="ps-label">'+esc(label)+'</span>'
    +badge
    +'</div>';
}

function updateSidebar(data){
  document.getElementById('procedureName').innerHTML=
    '<div class="pn-label">ACTIVE PROCEDURE</div>Procedure &mdash; '+data.total_steps+' steps';
  // Render Step 1 — additional steps are appended by appendSidebarStep()
  document.getElementById('procSteps').innerHTML=sidebarStepHTML(data.step,'current');
  setProgress(0);
}

function appendSidebarStep(step){
  // Mark previous step as completed in sidebar
  const prev=document.getElementById('ss_'+(step.step_number-1));
  if(prev){
    prev.className='proc-step completed';
    prev.querySelector('.ps-icon').textContent='✔';
    const b=prev.querySelector('.ps-badge');
    if(b){b.className='ps-badge done';b.textContent='DONE';}
  }
  // Add the new step to the sidebar list
  const list=document.getElementById('procSteps');
  const d=document.createElement('div');
  d.innerHTML=sidebarStepHTML(step,'current');
  list.appendChild(d.firstElementChild);
  // Scroll sidebar to show the new step
  list.scrollTop=list.scrollHeight;
  setProgress(Math.round((step.step_number/S.totalSteps)*100));
}

function setProgress(pct){
  document.getElementById('progressPct').textContent=pct+'%';
  document.getElementById('progressFill').style.width=pct+'%';
}

// Doc panel
function updateDocs(sources){
  if(!sources||!sources.length){
    document.getElementById('docEntries').innerHTML='<div class="doc-entry"><div class="de-source">SYSTEM</div><div class="de-title">No Sources</div><div class="de-snippet">No document references returned for this query.</div></div>';
    return;
  }

  const p=sources[0],sec=sources.slice(1);

  const secHTML=sec.length
    ? '<div class="de-secondary-block"><div class="de-also-label">ALSO REFERENCED</div>'
      + sec.map(s=>'<div class="de-secondary"><span class="de-sec-src">'+esc(s.source)+'</span><span class="de-sec-pg">P.'+s.page+'</span></div>').join('')
      + '</div>'
    : '';

  document.getElementById('docEntries').innerHTML=
    '<div class="doc-entry active">'
    + '<div class="de-source">'+esc(p.source)+'</div>'
    + '<div class="de-title">Page '+p.page+'</div>'
    + '<div class="de-snippet">Retrieved from technical knowledge base.</div>'
    + '<div class="de-score"><span class="de-score-label">RELEVANCE</span><div class="score-bar"><div class="score-fill" style="width:95%"></div></div><span class="de-pct">95%</span></div></div>'
    + secHTML;
}

// Language
function setLang(lang,el){
  S.lang=lang;
  document.querySelectorAll('.lang-btn').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  pickVoice();
  if(S.wakeRecog){stopWakeListener();setTimeout(startWakeListener,300);}
}

// Boot — tap-to-start overlay to unlock TTS + AudioContext
// Set voice toggle button to ON state on load (default is voice on)
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('voiceToggle');
  if(btn) btn.classList.add('active');
  const icon = document.getElementById('voiceIcon');
  if(icon) icon.textContent = '🔊';
  const lbl = document.getElementById('voiceLabel');
  if(lbl) lbl.textContent = 'VOICE ON';
});

(function(){
  // Boot overlay — click to unlock TTS and AudioContext.
  // Mic permission is handled by Chrome automatically for localhost.
  // No getUserMedia here — it's called once in startMicRecording on first use,
  // and Chrome on localhost remembers the permission permanently.
  const ov = document.createElement('div');
  ov.style.cssText = 'position:fixed;inset:0;z-index:9999;background:#003f72;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px;cursor:pointer;font-family:Arial,sans-serif;';
  ov.innerHTML =
    '<svg width="52" height="52" viewBox="-23 -23 46 46"><circle fill="#ffd54f" cx="0" cy="0" r="4.5" style="filter:drop-shadow(0 0 4px rgba(255,200,50,.9))"/><ellipse fill="none" stroke="rgba(100,200,255,.5)" stroke-width="1" cx="0" cy="0" rx="19" ry="6.5"/><ellipse fill="none" stroke="rgba(100,200,255,.5)" stroke-width="1" cx="0" cy="0" rx="19" ry="6.5" style="transform:rotate(60deg);transform-origin:0 0"/><ellipse fill="none" stroke="rgba(100,200,255,.5)" stroke-width="1" cx="0" cy="0" rx="19" ry="6.5" style="transform:rotate(120deg);transform-origin:0 0"/></svg>'
    + '<div style="font-size:32px;font-weight:700;letter-spacing:6px;color:#fff;">SHAKTI</div>'
    + '<div style="font-size:11px;color:#6ea8d8;letter-spacing:3px;">AI PROCEDURE ASSISTANT · INDUSTRIAL SYSTEM</div>'
    + '<div style="margin-top:8px;font-size:12px;color:#6ea8d8;letter-spacing:2px;border:1px solid rgba(255,255,255,.2);padding:10px 24px;border-radius:3px;animation:pt 1.5s ease-in-out infinite;">CLICK ANYWHERE TO START</div>'
    + '<style>@keyframes pt{0%,100%{opacity:.6}50%{opacity:1}}</style>';

  ov.addEventListener('click', () => {
    // 1. Unlock AudioContext (must happen in user gesture)
    getAudioCtx();

    // 2. Unlock browser TTS with a real audible word (Chrome autoplay policy)
    const _u = new SpeechSynthesisUtterance('Ready');
    _u.volume = 1; _u.rate = 1; _u.lang = 'en-IN';
    if(S.ttsVoice) _u.voice = S.ttsVoice;
    const _afterTTS = () => {
      // 3. Request mic — one getUserMedia for the whole session
      navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
          S.micStream = stream;
          ov.remove();
          pickVoice();
          startWakeListener();
        })
        .catch(() => {
          ov.remove();
          addSysMsg('Microphone permission denied. Please allow mic access and reload.');
        });
    };
    _u.onend = _afterTTS; _u.onerror = _afterTTS;
    speechSynthesis.cancel();
    speechSynthesis.speak(_u);
  }, { once: true });

  document.body.appendChild(ov);
})();