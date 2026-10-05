// The UI renders authoritative Rust status. All legality and search stay in WASM.
const $ = id => document.getElementById(id);
const worker = new Worker(new URL('worker.js', import.meta.url), {type:'module'});
let ready = false, busy = false, state = {size:15,rule:0,next:1,winner:0,board:'0'.repeat(225),history:[]}, forbids = new Set(), best = null, live = {p:null,winrate:null}, view = {rot:0,hflip:false,vflip:false,down:true,p2s:null,s2p:null}, started = 0, searchKind = null, pendingAuto = false, pendingRecord = false, appliedRecord = null, requestId = 0;
const canvas = $('board'), ctx = canvas.getContext('2d');
function notice(message='') { $('notice').textContent = message; $('notice').hidden = !message; }
function log(line) { const el=$('protocol-log'); el.textContent = (el.textContent + line + '\n').split('\n').slice(-700).join('\n'); el.scrollTop=el.scrollHeight; }
// 候选点标尺：胜率 0% 红 → 50% 琥珀 → 100% 绿，与 INFO WINRATE 同一口径（搜索方视角）
function winrateColor(value) { const w=Math.max(0,Math.min(1,value)); const hue=w<.5?12+33*(w/.5):45+90*((w-.5)/.5); return `hsl(${hue.toFixed(1)} 68% 45%)`; }
function resetLive() { live={p:null,winrate:null}; $('winrate').textContent='—'; $('winrate').style.color=''; $('balance-fill').style.width='50%'; $('balance-fill').style.background='#677b4b'; }
function showWinrate(value) { const w=Math.max(0,Math.min(1,value)), color=winrateColor(w); live.winrate=w; $('winrate').textContent=`${(w*100).toFixed(1)}%`; $('winrate').style.color=color; $('balance-fill').style.width=`${w*100}%`; $('balance-fill').style.background=color; }
// 视图坐标系：旋转/翻转只作用于显示与记谱，引擎收到的永远是画布原始坐标。
// p2s: 原始交点 → 屏幕交点；s2p: 屏幕交点 → 原始交点。字母恒为屏幕自左向右，数字方向可选。
function buildView() {
 const n=state.size, p2s=new Uint16Array(n*n), s2p=new Uint16Array(n*n);
 for(let y=0;y<n;y++)for(let x=0;x<n;x++){
  const fx=view.hflip?n-1-x:x, fy=view.vflip?n-1-y:y; let sx,sy;
  if(view.rot===1){sx=n-1-fy;sy=fx;} else if(view.rot===2){sx=n-1-fx;sy=n-1-fy;} else if(view.rot===3){sx=fy;sy=n-1-fx;} else {sx=fx;sy=fy;}
  const p=y*n+x, s=sy*n+sx; p2s[p]=s; s2p[s]=p;
 }
 view.p2s=p2s; view.s2p=s2p;
}
function screenXY(p) { const n=state.size, s=view.p2s[p]; return [s%n,(s/n)|0]; }
function labelOf(p) { const n=state.size, [sx,sy]=screenXY(p); return String.fromCharCode(97+sx)+(view.down?sy+1:n-sy); }
function recordOf(history) { return history.map(([p])=>labelOf(p)).join(''); }
function viewName() { const rot=['标准方向','旋转 90°','旋转 180°','旋转 270°'][view.rot], flips=[view.hflip?'水平翻转':null,view.vflip?'上下翻转':null].filter(Boolean); return `数字${view.down?'自上而下':'自下而上'} · ${flips.length?flips.join(' + ')+' + ':''}${rot}`; }
function parseRecord(text) {
 const n=state.size, clean=String(text).toLowerCase().replace(/[\s,;、]+/g,''), moves=[];
 if(!clean) throw Error('棋谱为空');
 let i=0;
 while(i<clean.length) {
  const code=clean.charCodeAt(i), sx=code-97;
  if(sx<0||sx>25) throw Error(`第 ${moves.length+1} 手应以字母开头：${clean.slice(i,i+4)}`);
  if(sx>=n) throw Error(`第 ${moves.length+1} 手的列 ${clean[i].toUpperCase()} 超出当前棋盘 a..${String.fromCharCode(96+n)}`);
  i++;
  let digits='';
  while(i<clean.length&&digits.length<2&&clean[i]>='0'&&clean[i]<='9') digits+=clean[i++];
  if(!digits) throw Error(`第 ${moves.length+1} 手缺少行号`);
  const row=Number(digits);
  if(row<1||row>n) throw Error(`第 ${moves.length+1} 手的行号 ${row} 超出当前棋盘 1..${n}（可在“对局设置”里换更大的棋盘）`);
  const sy=view.down?row-1:n-row, p=view.s2p[sy*n+sx];
  if(p===undefined) throw Error(`第 ${moves.length+1} 手坐标映射失败`);
  moves.push(p);
 }
 const seen=new Set();
 moves.forEach((p,k)=>{ if(seen.has(p)) throw Error(`第 ${k+1} 手重复落在 ${labelOf(p)}`); seen.add(p); });
 return moves;
}
function recordDraft() { const el=$('record'); el.classList.toggle('dirty',el.value!==recordOf(state.history)); }
function syncRecord(force=false) { const el=$('record'); if(force||document.activeElement!==el) el.value=recordOf(state.history); recordDraft(); $('record-count').textContent=`${state.history.length} 手`; $('view-state').textContent=viewName(); }
function send(lines) { if(!ready)return; if(typeof lines==='string')lines=[lines]; lines.forEach(x=>log('→ '+x)); worker.postMessage({type:'commands',lines,requestId:++requestId}); }
function settings() { return [`INFO timeout_turn ${$('time').value}`,`INFO max_depth ${Math.max(1,Number($('max-depth').value)||64)}`,`INFO max_node ${Math.max(1,Number($('max-nodes').value)||100000000)}`]; }
function rows(history=state.history, own=state.next, size=state.size) { return history.map(([p,c])=>`${p%size},${Math.floor(p/size)},${c===own?1:2}`); }
function sync(history=state.history, own=history.length%2+1, thinking=false) { return [thinking?'BOARD':'YXBOARD',...rows(history,own),'DONE']; }
function status() { send(['YXSTATUS', ...(Number($('rule').value)===2?['YXSHOWFORBID']:[])]); }
function setBusy(value) { busy=value; $('stop').disabled=!busy; $('engine-status').textContent=busy?'引擎思考中':ready?'引擎就绪 · 浏览器本地计算':'正在加载引擎'; $('engine-dot').className='dot '+(busy?'thinking':ready?'ready':''); for(const id of ['mode','rule','size','weights-file','record'])$(id).disabled=!ready||busy; for(const id of ['undo','analyze','new-game','play-best','use-hce','load-url'])$(id).disabled=!ready||busy||(id==='play-best'&&!best); }
function humanTurn() { return $('mode').value==='analysis'||state.next===($('mode').value==='black'?1:2); }
function search(suggest=false) { if(busy||pendingRecord||state.winner||state.history.length>=state.size**2)return; best=null; resetLive(); started=performance.now(); searchKind=suggest?'suggest':'move'; setBusy(true); send([...settings(),...sync(state.history,state.next,!suggest),...(suggest?['YXSUGGEST']:[])]); }
function newGame() { notice(); searchKind=null; setBusy(false); best=null; resetLive(); forbids.clear(); $('record').value=''; $('record').classList.remove('dirty'); pendingAuto=true; send([`START ${$('size').value}`,`INFO rule ${$('rule').value}`,'YXSTATUS',...(Number($('rule').value)===2?['YXSHOWFORBID']:[])]); }
// 切换模式（我执黑／我执白／自由摆棋）只改变由谁落子：棋盘和棋谱保持不动，不重开对局。
// YXBOARD 会用同一份历史完整重建引擎棋盘，因此这里只是原样重申当前局面。
// 之后若轮到引擎（例如轮到黑棋时切到“我执白”），就让它补上这一手；自由摆棋永远由人落子，不会触发应手。
function changeMode() { notice(); best=null; resetLive(); forbids.clear(); searchKind=null; if(busy)send('YXSTOP'); pendingAuto=true; send([...sync(state.history,state.next),'YXSTATUS',...(Number($('rule').value)===2?['YXSHOWFORBID']:[])]); }
function render() {
 const n=state.size, width=canvas.clientWidth||600, dpr=window.devicePixelRatio||1;canvas.width=width*dpr;canvas.height=width*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
 const pad=width*.065, step=(width-2*pad)/(n-1);ctx.fillStyle='#cfb98c';ctx.fillRect(0,0,width,width);ctx.strokeStyle='#796c50';ctx.lineWidth=.8;
 for(let i=0;i<n;i++){let p=pad+i*step;ctx.beginPath();ctx.moveTo(p,pad);ctx.lineTo(p,width-pad);ctx.moveTo(pad,p);ctx.lineTo(width-pad,p);ctx.stroke();}
 const stars=n===15?[3,7,11]:n===9?[2,4,6]:[];for(const x of stars)for(const y of stars){ctx.beginPath();ctx.arc(pad+x*step,pad+y*step,2.5,0,Math.PI*2);ctx.fillStyle='#796c50';ctx.fill();}
 ctx.font=`${Math.max(9,step*.28)}px system-ui`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle='#6d624d';for(let i=0;i<n;i++){ctx.fillText(String.fromCharCode(65+i),pad+i*step,pad*.37);ctx.fillText(String(view.down?i+1:n-i),pad*.37,pad+i*step);}
 for(let p=0;p<n*n;p++){const c=Number(state.board[p]),[sx,sy]=screenXY(p),x=pad+sx*step,y=pad+sy*step;if(c){const g=ctx.createRadialGradient(x-step*.12,y-step*.13,0,x,y,step*.44);g.addColorStop(0,c===1?'#606060':'#fff');g.addColorStop(1,c===1?'#111':'#d4d2c8');ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,step*.43,0,Math.PI*2);ctx.shadowColor='#0005';ctx.shadowBlur=3;ctx.shadowOffsetY=2;ctx.fill();ctx.shadowBlur=ctx.shadowOffsetY=0;}else if(forbids.has(p)&&state.next===1){ctx.strokeStyle='#a14c3d';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(x-3,y-3);ctx.lineTo(x+3,y+3);ctx.moveTo(x+3,y-3);ctx.lineTo(x-3,y+3);ctx.stroke();}}
 const last=state.history.at(-1);if(last){const [sx,sy]=screenXY(last[0]);ctx.fillStyle=last[1]===1?'#d7de9a':'#627340';ctx.beginPath();ctx.arc(pad+sx*step,pad+sy*step,step*.09,0,Math.PI*2);ctx.fill();}
 if(best&&!busy){const [sx,sy]=screenXY(best[1]*n+best[0]);ctx.strokeStyle='#ab3f2b';ctx.lineWidth=2;ctx.beginPath();ctx.arc(pad+sx*step,pad+sy*step,step*.42,0,Math.PI*2);ctx.stroke();}
 // 搜索中实时候选点：颜色随 INFO WINRATE 变化，并在点上标注胜率
 if(live.p!==null&&live.winrate!==null){const [sx,sy]=screenXY(live.p),x=pad+sx*step,y=pad+sy*step,r=step*.33,label=`${Math.round(live.winrate*100)}%`;
  ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=winrateColor(live.winrate);ctx.fill();ctx.lineWidth=1.5;ctx.strokeStyle='rgba(20,28,20,.55)';ctx.stroke();
  ctx.font=`600 ${Math.max(9,step*.3)}px system-ui`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.lineWidth=3;ctx.strokeStyle='rgba(14,20,14,.85)';ctx.strokeText(label,x,y);ctx.fillStyle='#fff';ctx.fillText(label,x,y);}
 $('turn-stone').className='mini-stone '+(state.next===1?'black':'white');$('turn-text').textContent=state.winner?`${state.winner===1?'黑':'白'}方获胜`:`${state.next===1?'黑':'白'}方落子`;$('move-counter').textContent=`第 ${state.history.length} 手`;$('position-status').textContent=state.winner?'对局结束':state.history.length===n*n?'棋盘已满':busy?'正在搜索…':humanTurn()?'点击交点落子':'等待引擎落子';
}
function play(x,y) { if(!ready||busy||pendingRecord||state.winner)return;notice();best=null;pendingAuto=true;send([...sync(state.history,state.next),`PLAY ${x},${y}`,'YXSTATUS',...(state.rule===2?['YXSHOWFORBID']:[])]); }
canvas.addEventListener('click',event=>{if(!humanTurn())return;const r=canvas.getBoundingClientRect(),pad=r.width*.065,step=(r.width-2*pad)/(state.size-1),sx=Math.round((event.clientX-r.left-pad)/step),sy=Math.round((event.clientY-r.top-pad)/step);if(sx<0||sy<0||sx>=state.size||sy>=state.size)return;const p=view.s2p[sy*state.size+sx];play(p%state.size,Math.floor(p/state.size));});
new ResizeObserver(render).observe(canvas);
worker.onmessage=({data})=>{
 if(data.type==='ready'){ready=true;setBusy(false);newGame();return;}
 if(data.type==='error'){notice(data.error);searchKind=null;pendingRecord=false;setBusy(false);if(!ready){$('engine-status').textContent='引擎加载失败';$('engine-dot').className='dot error';}return;}
 if(data.type==='weights'){if(data.ok){$('evaluator-tag').textContent='NNUE';$('weights-name').textContent=`已加载 ${data.name} · SHA-256 ${data.hash}`;notice();}else notice('权重格式校验失败，保留原评估器。');return;}
 if(data.type==='busy'){if(data.requestId===requestId){setBusy(data.busy);if(!data.busy)searchKind=null;render();}return;}
 if(data.type==='idle'){render();return;}
 if(data.type!=='line')return; const line=data.line;log('← '+line);
 if(line.startsWith('ERROR ')){notice(line.slice(6));pendingAuto=false;pendingRecord=false;if(searchKind){searchKind=null;setBusy(false);}resetLive();render();}
 if(line.startsWith('MESSAGE STATUS ')){try{state=JSON.parse(line.slice(15));$('size').value=state.size;$('rule').value=state.rule;forbids.clear();pendingRecord=false;resetLive();buildView();syncRecord();render();if(pendingAuto){pendingAuto=false;if(!humanTurn()&&!state.winner)search();}}catch(e){notice(`状态解析失败: ${e}`);}return;}
 if(line.startsWith('FORBID ')){forbids.clear();const s=line.slice(7).replace(/\.$/,'');for(let i=0;i+3<s.length;i+=4){const x=Number(s.slice(i,i+2)),y=Number(s.slice(i+2,i+4));forbids.add(y*state.size+x);}render();return;}
 const move=line.match(/^(SUGGEST )?(\d+),(\d+)$/);if(move){if(move[1]){best=[+move[2],+move[3]];searchKind=null;setBusy(false);render();}else if(searchKind==='move'){setBusy(false);searchKind=null;status();}return;}
 if(line.startsWith('MESSAGE REALTIME BEST ')){const [x,y]=line.slice(22).split(',').map(Number);if(Number.isFinite(x)&&Number.isFinite(y)){live.p=y*state.size+x;render();}return;}
 if(line.startsWith('INFO ')){const [,key,...tail]=line.split(' '),v=tail.join(' ');
  if(key==='DEPTH')$('depth').textContent=v;
  if(key==='NODES')$('nodes').textContent=Number(v).toLocaleString();
  if(key==='EVAL'){$('eval-value').textContent=v;$('eval-caption').textContent='搜索方视角';}
  if(key==='WINRATE'&&Number.isFinite(Number(v)))showWinrate(Number(v));
  if(key==='BESTLINE'){const pv=v.split(/\s+/).filter(Boolean);$('pv').replaceChildren(...pv.map(item=>{const s=document.createElement('span');s.className='pv-move';const [x,y]=item.split(',').map(Number);s.textContent=Number.isFinite(x)&&Number.isFinite(y)?labelOf(y*state.size+x).toUpperCase():item;return s;}));
   // PV 的第一个着法就是引擎当前认为的最佳候选点，点上标注同一次迭代的 WINRATE
   const [x,y]=(pv[0]||'').split(',').map(Number);live.p=Number.isFinite(x)&&Number.isFinite(y)?y*state.size+x:null;render();}
  $('elapsed').textContent=`${((performance.now()-started)/1000).toFixed(1)} s`;}
};
$('new-game').onclick=newGame;for(const id of ['rule','size'])$(id).onchange=()=>{if(busy)send('YXSTOP');newGame();};$('mode').onchange=changeMode;
$('stop').onclick=()=>send('YXSTOP');$('analyze').onclick=()=>search(true);$('play-best').onclick=()=>{if(best)play(...best);};
$('undo').onclick=()=>{if(pendingRecord||!state.history.length)return;best=null;const count=$('mode').value==='analysis'?1:humanTurn()&&state.history.length>1?2:1;const history=state.history.slice(0,-count);send([...sync(history,history.length%2+1),'YXSTATUS',...(state.rule===2?['YXSHOWFORBID']:[])]);};
// 棋谱：填写的文本按当前视图坐标系解析，合法即交给引擎做权威校验后应用；轮到引擎就照常应手。
// 只在「确认」时应用 —— 输入框失焦，或按回车（棋谱是单行输入，回车不换行、只当确认）；
// 输入过程中不应用，避免打到一半的棋谱被当成正式局面。
function applyRecord(text, quiet=false) {
 if(!ready) return;
 const value=String(text??'');
 if(pendingRecord&&value===appliedRecord) return;   // 同一份棋谱还在等引擎确认，别重复提交
 if(busy) { if(!quiet) notice('引擎正在思考，先停止再填入棋谱。'); return; }
 if(!value.trim()) { if(!quiet) notice('棋谱为空，已恢复为当前棋谱。'); syncRecord(true); return; }
 let moves;
 try { moves=parseRecord(value); }
 catch(e) { if(!quiet){ notice(`棋谱不合法：${e.message}`); syncRecord(true); } return; }
 const history=moves.map((p,k)=>[p,k%2+1]);
 if(history.length===state.history.length&&history.every((m,k)=>m[0]===state.history[k][0])) { if(!quiet) notice(); syncRecord(true); return; }
 notice(); best=null; resetLive(); pendingAuto=true; pendingRecord=true; forbids.clear(); appliedRecord=value;
 const field=$('record'); field.value=history.map(([p])=>labelOf(p)).join(''); field.classList.remove('dirty');
 send(['START '+state.size,`INFO rule ${$('rule').value}`,'YXBOARD',...rows(history,history.length%2+1,state.size),'DONE','YXSTATUS',...(Number($('rule').value)===2?['YXSHOWFORBID']:[])]);
}
$('record').addEventListener('input',()=>{
 const el=$('record');
 if(/[\r\n]/.test(el.value)) {
  const before=el.value, at=el.selectionStart;
  el.value=before.replace(/[\r\n]+/g,'');
  const caret=Math.max(0,at-(before.length-el.value.length));
  try { el.setSelectionRange(caret,caret); } catch(e) {}
 }
 recordDraft();
});
$('record').addEventListener('keydown',e=>{
 if(e.key!=='Enter'||e.isComposing||e.keyCode===229) return;
 e.preventDefault();
 applyRecord($('record').value);
});
$('record').addEventListener('change',()=>applyRecord($('record').value));
$('record-copy').onclick=async()=>{ const text=recordOf(state.history); try{ await navigator.clipboard.writeText(text); notice(text?`已复制棋谱：${text}`:'当前还没有棋子，棋谱为空。'); }catch(e){ $('record').select(); notice('浏览器拒绝了剪贴板写入，棋谱已选中，请手动复制。'); } };
function applyView() { if(view.hflip&&view.vflip){ view.hflip=false; view.vflip=false; view.rot=(view.rot+2)%4; } buildView(); syncRecord(true); render(); }
$('rotate-cw').onclick=()=>{ view.rot=(view.rot+1)%4; applyView(); };
$('rotate-ccw').onclick=()=>{ view.rot=(view.rot+3)%4; applyView(); };
$('flip-horizontal').onclick=()=>{ view.hflip=!view.hflip; applyView(); };
$('flip-vertical').onclick=()=>{ view.vflip=!view.vflip; applyView(); };
$('reset-view').onclick=()=>{ view.rot=0; view.hflip=false; view.vflip=false; applyView(); };
$('row-direction').onchange=event=>{ view.down=event.target.value==='down'; applyView(); };
async function weights(bytes,name){if(!ready||busy)throw Error('请先等待引擎就绪并停止思考');const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');worker.postMessage({type:'weights',bytes,name,hash},[bytes]);}
$('weights-file').onchange=async e=>{try{const f=e.target.files[0];if(f)await weights(await f.arrayBuffer(),f.name);}catch(err){notice(err.message);}e.target.value='';};
$('load-url').onclick=async()=>{try{if(busy)throw Error('请先停止思考');const url=new URL($('weights-url').value,location.href);if(!['https:','http:'].includes(url.protocol))throw Error('请使用 HTTP 或 HTTPS URL');const response=await fetch(url);if(!response.ok)throw Error(`下载失败: HTTP ${response.status}`);await weights(await response.arrayBuffer(),url.pathname.split('/').at(-1)||url.hostname);}catch(e){notice(`加载失败: ${e.message}。跨域地址需要允许 CORS。`);}};
$('use-hce').onclick=()=>{send('YXUNLOADNNUE');$('evaluator-tag').textContent='HCE 基线';$('weights-name').textContent='当前使用手写棋形评估，不需要权重。';notice();};
$('command-form').onsubmit=e=>{e.preventDefault();const value=$('command-input').value.trim();if(value){if(/^(BEGIN|BOARD|YXGO|TURN|YXSUGGEST)\b/i.test(value)){searchKind=/^YXSUGGEST\b/i.test(value)?'suggest':'move';started=performance.now();setBusy(true);}send(value.split('\n'));$('command-input').value='';if(!busy)status();}};$('clear-log').onclick=()=>{$('protocol-log').textContent='';};
$('row-direction').value=view.down?'down':'up';buildView();syncRecord();render();setBusy(false);worker.postMessage({type:'init'});
