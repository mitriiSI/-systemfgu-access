/* A stable day strip: native inertia, one-day navigation and a sliding window. */
function subjectTitle(value){
 let text=String(value||'').replace(/\s+/g,' ').trim();
 if(/^(?:[А-Яа-яЁё]\s+){3,}[А-Яа-яЁё]$/.test(text))text=text.replaceAll(' ','');
 return text.replace(/\s*[-–]\s*/g,'-').toLocaleLowerCase('ru-RU').replace(/[a-zа-яё]/i,letter=>letter.toLocaleUpperCase('ru-RU'));
}
function subjectDisplay(value){
 for(const day of days)for(const lesson of day.lessons)for(const period of lesson.periods)if(period.disciplineFullName===value)return subjectTitle(period._diary_title||value);
 return subjectTitle(value);
}

function buildDayNavigation(host){
 const eyebrow=node('p','eyebrow'),heading=node('h1'),hints=node('div','day-hints');
 host.append(eyebrow,heading,hints);subgroupHint(hints);importChoicesHint(hints);
 const tools=node('div','week-tools'),calendarControl=node('div','day-calendar-controls'),caption=node('span');
 const calendarIcon=iconButton('calendar','Открыть календарь',()=>go('calendar')),alignControl=button('',()=>alignWeek(),'week-align');
 alignControl.setAttribute('aria-label','Выровнять выбранную неделю от понедельника до воскресенья');alignControl.title='Показать неделю ровно';alignControl.append(caption);calendarControl.append(calendarIcon,alignControl);
 tools.append(iconButton('back','Предыдущий день',()=>changeDay(addDays(selectedDay,-1))),calendarControl,iconButton('forward','Следующий день',()=>changeDay(addDays(selectedDay,1))));
 const strip=node('div','week day-strip'),viewport=node('div','day-viewport'),track=node('div','day-track');
 viewport.setAttribute('aria-label','Дни расписания');viewport.append(track);strip.append(viewport);host.append(tools,strip);
 const details=node('div','day-details');host.append(details);if(typeof mountGroupComparison==='function')mountGroupComparison(host);
 let first='',width=0,settleTimer=0,pending='',pendingLeft=0,drag=null,suppressClick=false,disposed=false,userScrolling=false,gestureDate='',gestureLeft=0;
 const distance=(a,b)=>Math.round((Date.parse(a+'T12:00:00Z')-Date.parse(b+'T12:00:00Z'))/86400000);
 const motion=()=>!matchMedia('(prefers-reduced-motion: reduce)').matches;
 function updateLabels(value){
  eyebrow.textContent=value===today()?'СЕГОДНЯ':'РАСПИСАНИЕ';heading.textContent=dateLabel(value);
  const monday=addDays(value,-((new Date(value+'T12:00:00Z').getUTCDay()+6)%7));
  caption.textContent=monday.split('-').reverse().join('.')+' — '+addDays(monday,6).split('-').reverse().join('.');
  for(const cell of track.children){const active=cell.dataset.date===value;cell.classList.toggle('active',active);cell.setAttribute('aria-pressed',String(active));cell.tabIndex=active?0:-1;}
 }
 function rebuild(value){
  first=addDays(value,-45);const cells=document.createDocumentFragment();
  for(let i=0;i<91;i++){
   const date=addDays(first,i),day=(new Date(date+'T12:00:00Z').getUTCDay()+6)%7;
   const cell=button('',()=>changeDay(date),'day-cell');cell.dataset.date=date;
   cell.append(node('small',null,weekdays[day]),node('strong',null,String(Number(date.slice(-2)))));
   cell.setAttribute('aria-label',new Date(date+'T12:00:00Z').toLocaleDateString(uiLocale(),{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}));
   if(date===today())cell.setAttribute('aria-current','date');cells.append(cell);
  }
  track.replaceChildren(cells);updateLabels(value);
 }
 function indexAtCenter(){return Math.round(viewport.scrollLeft/width)+3;}
 function measure(){
  const next=viewport.clientWidth/7;if(!next||Math.abs(next-width)<.1)return;
  userScrolling=false;width=next;viewport.style.setProperty('--day-width',width+'px');alignWeek(true);
 }
 function alignWeek(instant=false){
  userScrolling=false;
  const offset=(new Date(selectedDay+'T12:00:00Z').getUTCDay()+6)%7;
  pending=selectedDay;pendingLeft=(distance(selectedDay,first)-offset)*width;
  viewport.scrollTo({left:pendingLeft,behavior:instant||!motion()?'auto':'smooth'});
 }
 function settle(){
  clearTimeout(settleTimer);if(disposed||!host.isConnected||!width||drag)return;
  const index=indexAtCenter(),date=addDays(first,index);
  if(pending){if(Math.abs(viewport.scrollLeft-pendingLeft)>2)return;pending='';return;}
  if(!userScrolling)return;userScrolling=false;
  const value=addDays(gestureDate,Math.round((viewport.scrollLeft-gestureLeft)/width));
  if(index<16||index>74){rebuild(date);viewport.scrollLeft=42*width;}
  if(value!==selectedDay)changeDay(value,{fromScroll:true}).catch(fail);
 }
 function select(value,{fromScroll=false}={}){
  userScrolling=false;
  let index=distance(value,first);
  if(index<3||index>87){rebuild(value);updateLabels(value);alignWeek(true);return;}
  updateLabels(value);
  if(!fromScroll){pending=value;pendingLeft=(index-3)*width;viewport.scrollTo({left:pendingLeft,behavior:motion()?'smooth':'auto'});}
 }
 viewport.addEventListener('scroll',()=>{clearTimeout(settleTimer);settleTimer=setTimeout(settle,180);},{passive:true});
 viewport.addEventListener('scrollend',settle);
 function beginScroll(){if(!userScrolling){gestureDate=selectedDay;gestureLeft=viewport.scrollLeft;}pending='';userScrolling=true;}
 viewport.addEventListener('wheel',beginScroll,{passive:true});
 viewport.addEventListener('pointerdown',event=>{
  beginScroll();suppressClick=false;
  if(event.isPrimary&&event.pointerType==='mouse'&&event.button===0)drag={id:event.pointerId,x:event.clientX,left:viewport.scrollLeft,moved:false};
 },{passive:true});
 viewport.addEventListener('pointermove',event=>{
  if(!drag||event.pointerId!==drag.id)return;const dx=event.clientX-drag.x;
  if(!drag.moved&&Math.abs(dx)<6)return;
  if(!drag.moved){drag.moved=true;viewport.setPointerCapture(event.pointerId);viewport.classList.add('is-dragging');}
  event.preventDefault();viewport.scrollLeft=drag.left-dx;
 });
 function finish(event){
  if(!drag||event.pointerId!==drag.id)return;suppressClick=drag.moved;drag=null;viewport.classList.remove('is-dragging');
  if(viewport.hasPointerCapture(event.pointerId))viewport.releasePointerCapture(event.pointerId);
  if(suppressClick){const left=(indexAtCenter()-3)*width;viewport.scrollTo({left,behavior:motion()?'smooth':'auto'});settleTimer=setTimeout(settle,180);}
 }
 for(const type of ['pointerup','pointercancel','lostpointercapture'])viewport.addEventListener(type,finish);
 viewport.addEventListener('click',event=>{if(suppressClick){event.preventDefault();event.stopPropagation();suppressClick=false;}else userScrolling=false;},true);
 viewport.addEventListener('keydown',event=>{
  const step=event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:0;if(!step)return;
  event.preventDefault();const value=addDays(selectedDay,step);changeDay(value).catch(fail);track.querySelector('[data-date="'+value+'"]')?.focus({preventScroll:true});
 });
 rebuild(selectedDay);const resize=new ResizeObserver(measure);resize.observe(viewport);measure();
 const lifecycle=new MutationObserver(()=>{if(!host.isConnected){disposed=true;resize.disconnect();lifecycle.disconnect();clearTimeout(settleTimer);}});
 lifecycle.observe(host.parentNode,{childList:true});
 return {details,select,update:()=>updateLabels(selectedDay)};
}

function refreshDayView({animate=false,direction=1}={}){
 const host=screen.querySelector('.day-page'),navigation=host?.dayNavigation;if(!navigation)return;
 navigation.update();if(typeof refreshGroupComparison==='function')refreshGroupComparison(host);const details=navigation.details;details.replaceChildren();details.removeAttribute('aria-busy');renderDayDetails(details);
 if(animate&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
  details.getAnimations().forEach(animation=>animation.cancel());
  details.animate([{opacity:.55,transform:'translateX('+(direction*8)+'px)'},{opacity:1,transform:'translateX(0)'}],{duration:220,easing:'cubic-bezier(.2,.7,.2,1)'});
 }
}

/* One persistent brand follows its anchor and settles like a small glass drop. */
(() => {
 const host=document.getElementById('fgu-diary-design'),header=host.querySelector('.fd-telegram');
 const motion=matchMedia('(prefers-reduced-motion: reduce)');
 let brand,anchor,label,frame=0,x=0,y=0,vx=0,vy=0,initialized=false;
 function mount(){
  const inline=header.querySelector('.brand-capsule');if(!inline)return;
  const box=inline.getBoundingClientRect();
  if(!brand){
   brand=inline;anchor=document.createElement('div');anchor.className='brand-anchor';anchor.setAttribute('aria-hidden','true');
   label=document.createElement('span');label.className='brand-label';label.textContent='Midiary';label.dataset.noTranslate='';brand.replaceChildren(label);
   x=box.left+box.width/2;y=box.top;brand.classList.add('floating-brand');brand.dataset.brandMotion='fluid';
  }
  anchor.style.width=box.width+'px';anchor.style.height=box.height+'px';inline.replaceWith(anchor);host.append(brand);initialized=false;
  sizes.observe(brand);paint();
 }
 function paint(){
  frame=0;if(!brand||!anchor?.isConnected)return;
  const hidden=!header.getClientRects().length;if(brand.hidden!==hidden)brand.hidden=hidden;if(hidden)return;
  const box=anchor.getBoundingClientRect(),safe=parseFloat(getComputedStyle(brand).top)||12;
  const progress=Math.min(1,Math.max(0,(safe-box.top)/64));
  const tx=(box.left+box.width/2)*(1-progress)+innerWidth/2*progress,ty=Math.max(safe,box.top);
  if(!initialized||motion.matches){x=tx;y=ty;vx=vy=0;initialized=true;}
  else{vx=(vx+(tx-x)*.16)*.72;vy=(vy+(ty-y)*.16)*.72;x+=vx;y=Math.max(safe,y+vy);}
  const flowX=motion.matches?0:Math.min(.075,Math.abs(vx)*.004),flowY=motion.matches?0:Math.min(.065,Math.abs(vy)*.004);
  const sx=1+flowX-flowY*.4,sy=1+flowY-flowX*.4,angle=motion.matches?0:Math.max(-1.8,Math.min(1.8,-vx*.12));
  brand.style.transform='translate3d('+(x-brand.offsetWidth/2)+'px,'+(y-safe)+'px,0) rotate('+angle+'deg) scale('+sx+','+sy+')';
  label.style.transform='scale('+(1/sx)+','+(1/sy)+') rotate('+(-angle)+'deg)';
  host.dispatchEvent(new Event('midiary:brand-motion'));
  if(Math.abs(tx-x)+Math.abs(ty-y)+Math.abs(vx)+Math.abs(vy)>.08)frame=requestAnimationFrame(paint);
 }
 function schedule(){if(!frame)frame=requestAnimationFrame(paint);}
 const sizes=new ResizeObserver(()=>{if(brand&&anchor){anchor.style.width=brand.offsetWidth+'px';anchor.style.height=brand.offsetHeight+'px';}schedule();});
 sizes.observe(header);new MutationObserver(()=>{mount();schedule();}).observe(header,{childList:true,subtree:true});
 window.addEventListener('scroll',schedule,{passive:true});window.addEventListener('resize',schedule,{passive:true});
 motion.addEventListener('change',schedule);document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0;}else schedule();});mount();
})();
