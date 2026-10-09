// Personal history points. Amounts and ownership are validated by the server.
let historyPointTotals=[],historyPointTotal=0,historyPointTerm='',historyPointSeed='',historyPointAdding=false,historyPointRevision=0;
const historyPointCopy={
 ru:{menu:'Баллы',heading:'Баллы по истории',total:'Итого',add:'Добавить баллы',points:'Баллы',save:'Добавить',saved:'Баллы сохранены',short:'Итог',home:'Вернуться к сегодняшнему расписанию'},
 en:{menu:'Points',heading:'History points',total:'Total',add:'Add points',points:'Points',save:'Add',saved:'Points saved',short:'Total',home:'Return to today’s schedule'},
 zh:{menu:'积分',heading:'历史课程积分',total:'总分',add:'添加积分',points:'积分',save:'添加',saved:'积分已保存',short:'总分',home:'返回今天的课表'}
};
function hpText(key){return (historyPointCopy[uiLanguage()]||historyPointCopy.ru)[key];}
function hpNode(tag,cls,text){const result=node(tag,cls,text);result.dataset.noTranslate='';return result;}
function hpButton(text,action,cls='fd-secondary'){const result=button(text,action,cls);result.dataset.noTranslate='';return result;}
function historyPointAmount(value){return new Intl.NumberFormat(uiLocale(),{maximumFractionDigits:2}).format(value);}
function isHistorySubject(title){return /^(?:история(?: россии| отечества)?|отечественная история|history(?: of russia)?|俄罗斯历史)$/i.test(String(title||'').replace(/\s+/g,' ').trim());}
function isHistorySeminar(lesson){return isHistorySubject(lesson.title)&&/сем|seminar|\bsem\b/i.test(lesson.type||'');}
function weeklyHistorySeminar(lesson){
 if(!isHistorySeminar(lesson))return false;
 const monday=addDays(lesson.date,-((new Date(lesson.date+'T12:00:00Z').getUTCDay()+6)%7)),sunday=addDays(monday,6);
 const seminars=days.filter(day=>day.date>=monday&&day.date<=sunday).flatMap(day=>lessons(day.date)).filter(isHistorySeminar);
 seminars.sort((a,b)=>(a.date+'|'+a.start+'|'+a.key).localeCompare(b.date+'|'+b.start+'|'+b.key));
 return seminars[0]?.key===lesson.key;
}
function historyPointsBadge(host,lesson){
 if(!weeklyHistorySeminar(lesson))return;
 const total=historyPointTotal;
 const badge=hpButton(hpText('short')+': '+historyPointAmount(total),()=>openHistoryPoints(lesson),'history-points-badge');
 badge.setAttribute('aria-label',hpText('heading')+' · '+hpText('total')+': '+historyPointAmount(total));
 host.append(badge);
}
async function openHistoryPoints(lesson,adding=false){
 await go('history-points');
}
async function returnToToday(){
 if(!me)return;
 if(me.needs_group){await go('study-group');return;}
 if(page==='day'&&!fileView){await changeDay(today());window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});return;}
 selectedDay=today();await go('day');
}
function wireHistoryNavigation(){
 const nav=document.getElementById('nav'),old=nav.querySelector('[data-page="day"]');
 if(old){
  const next=hpButton(hpText('menu'),()=>go('history-points'));next.dataset.page='history-points';
  const graphic=document.createElementNS('http://www.w3.org/2000/svg','svg');
  graphic.setAttribute('viewBox','0 0 24 24');graphic.setAttribute('fill','none');graphic.setAttribute('stroke','currentColor');graphic.setAttribute('stroke-linecap','round');graphic.setAttribute('stroke-linejoin','round');graphic.setAttribute('aria-hidden','true');
  graphic.innerHTML='<path d="M4 3v18h17"/><path class="icon-points-bars" d="M8 17v-5m5 5V8m5 9V5"/>';
  next.replaceChildren(graphic,hpNode('span',null,hpText('menu')));old.replaceWith(next);
 }
 const label=nav.querySelector('[data-page="history-points"] span');if(label){label.dataset.noTranslate='';label.textContent=hpText('menu');}
 const brand=root.querySelector('.brand-capsule');
 if(brand){
  brand.setAttribute('aria-label',hpText('home'));brand.title=hpText('home');
  if(brand.tagName!=='BUTTON'){brand.setAttribute('role','button');brand.tabIndex=0;brand.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();returnToToday().catch(fail);}};}
  brand.onclick=()=>returnToToday().catch(fail);
 }
}
async function historyPointsPage(host){
 const generation=loginGeneration,group=me?.group_id,result=await api('history-points?simple=1');
 if(!host.isConnected||page!=='history-points'||generation!==loginGeneration||group!==me?.group_id)return;
 host.classList.add('history-points-page');host.append(hpNode('h1',null,hpText('heading')));
 const form=node('form','history-points-form'),label=hpNode('label','fd-label',hpText('points')),points=node('input','fd-input');
 points.type='number';points.required=true;points.min=0;points.max=1000;points.step='.01';points.inputMode='decimal';points.placeholder='0';points.setAttribute('aria-label',hpText('points'));label.append(points);
 const save=hpNode('button','fd-primary',hpText('save'));save.type='submit';
 const status=hpNode('p','muted history-points-status');status.setAttribute('role','status');form.append(label,save,status);
 const summary=node('section','history-points-summary'),total=hpNode('strong','history-points-total',historyPointAmount(result.total));
 summary.setAttribute('aria-live','polite');summary.setAttribute('aria-atomic','true');summary.append(hpNode('span',null,hpText('total')),total);host.append(form,summary);
 historyPointTotal=result.total;
 form.onsubmit=async event=>{
  event.preventDefault();if(save.disabled||!form.reportValidity())return;save.disabled=true;status.textContent='';document.getElementById('status').textContent='';
  try{
   await post('history-points',{points:Number(points.value)});
   if(generation!==loginGeneration||group!==me?.group_id)return;
   points.value='';delete form.dataset.dirty;await refreshHistoryPointTotals();
   if(host.isConnected&&page==='history-points'&&generation===loginGeneration){total.textContent=historyPointAmount(historyPointTotal);}
  }catch(error){if(host.isConnected&&generation===loginGeneration)status.textContent=error.message;}finally{save.disabled=false;}
 };
}
async function refreshHistoryPointTotals(){const generation=loginGeneration,group=me?.group_id,revision=++historyPointRevision,result=await api('history-points/summary');if(me&&generation===loginGeneration&&group===me.group_id&&revision===historyPointRevision){historyPointTotals=result.totals;historyPointTotal=result.total;lastLoadAt=0;}}
