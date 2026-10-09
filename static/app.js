const root=document.getElementById('fgu-diary-design'),screen=document.getElementById('screen'),tg=window.Telegram?.WebApp;
let csrf='',me,days=[],contents=[],personal=[],topics=[],scheduleEvents=[],selectedDay=new Date().toLocaleDateString('sv-SE',{timeZone:'Europe/Moscow'}),selectedLesson,selectedTeacher='',page='day',history=[],scheduleInfo={};
let pendingRequests=0,refreshInFlight=false;
screen.addEventListener('input',markDirty);screen.addEventListener('change',markDirty);
function markDirty(event){const form=event.target.closest('form');if(form)form.dataset.dirty='true';}
const weekdays=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
function privateEditor(host,kind,item,label){
 const form=node('form','fd-note-form'),input=node('textarea','fd-input fd-textarea');
 input.value=personal.find(x=>x.kind===kind&&x.item===item)?.body||'';input.maxLength=20000;input.setAttribute('aria-label',label);
 const submit=node('button','fd-primary','Сохранить личную запись');submit.type='submit';const status=node('p','muted');status.setAttribute('role','status');
 form.append(node('h2',null,label),node('p','muted','Видно только тебе'),input,submit,status);host.append(form);
 form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{await post('personal',{kind,item,body:input.value});personal=await api('personal');delete form.dataset.dirty;status.textContent='Сохранено';}catch(e){fail(e);}finally{submit.disabled=false;}};
}
function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;if(text&&((me&&text===me.name)||(selectedTeacher&&text===selectedTeacher)||(cls&&['rating-avatar','fd-photo-placeholder'].includes(cls))))n.dataset.personName='';return n;}
function button(text,fn,cls='fd-secondary'){const b=node('button',cls,text);b.type='button';b.onclick=()=>Promise.resolve().then(fn).catch(fail);return b;}
function fail(e){document.getElementById('status').textContent=e.message||'Не удалось выполнить действие';}
async function api(path,options={}){
 const headers={'X-Midiary-Language':uiLanguage(),'X-CSRF-Token':csrf,...options.headers};if(options.body&&!(options.body instanceof FormData)){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}
 pendingRequests++;root.classList.add('is-loading');
 try{
  let r;try{r=await fetch('/api/'+path,{...options,headers});}catch{throw Error('Нет соединения. Проверьте интернет и попробуйте ещё раз.');}
  let data;try{data=await r.json();}catch{const error=Error('Сервер временно недоступен. Попробуйте ещё раз.');error.status=r.status;throw error;}
  if(!r.ok){const error=Error(data.error||'Ошибка сервера');error.status=r.status;throw error;}return data;
 }finally{pendingRequests--;root.classList.toggle('is-loading',pendingRequests>0);}}
function post(path,body){return api(path,{method:'POST',body});}
function today(){return new Date().toLocaleDateString('sv-SE',{timeZone:'Europe/Moscow'});}
function dateLabel(d){return new Date(d+'T12:00:00Z').toLocaleDateString(uiLocale(),{day:'numeric',month:'long'});}
function addDays(d,n){const x=new Date(d+'T12:00:00Z');x.setUTCDate(x.getUTCDate()+n);return x.toISOString().slice(0,10);}
function content(kind,item){return contents.find(x=>x.kind===kind&&x.item===item)?.body||'';}
function lessonHomework(lesson){
 const exact=contents.find(row=>row.kind==='homework'&&row.item===lesson.key);if(exact)return exact.body;
 if(lesson.subgroup&&!lesson.group){const legacy=lesson.key.split('|');legacy[legacy.length-1]='';return content('homework',legacy.join('|'));}return '';
}
function identity(host){
 updateHeaderIdentity();
}
function theme(value){
 value=value==='dark'?'dark':'light';root.dataset.theme=value;
 document.documentElement.dataset.fguTheme=value;document.documentElement.style.colorScheme=value;
 document.documentElement.style.backgroundColor=value==='dark'?'#080808':'#f4f4f5';
 document.querySelector('meta[name="theme-color"]').content=value==='dark'?'#080808':'#f4f4f5';
 const toggle=document.getElementById('theme');toggle.replaceChildren(icon(value==='dark'?'sun':'moon'));
 toggle.setAttribute('aria-label',value==='dark'?'Включить светлую тему':'Включить тёмную тему');
 try{localStorage.setItem('fgu-theme',value);}catch{}
}
document.getElementById('theme').onclick=()=>{const value=root.dataset.theme==='light'?'dark':'light';theme(value);if(me)post('theme',{theme:value}).catch(fail);};
function updateBack(){document.getElementById('back').disabled=!me;document.getElementById('logout').hidden=!me;updateHeaderIdentity();if(typeof wireHistoryNavigation==='function')wireHistoryNavigation();}
document.getElementById('back').onclick=()=>{if(fileView){closeFile();return;}if(me)go(history.pop()||(page==='day'?'calendar':'day'),false);};
updateBack();
document.querySelectorAll('#nav [data-page]').forEach(b=>b.onclick=()=>{if(b.dataset.page==='day'&&page==='day')return changeDay(today());if(b.dataset.page==='day')selectedDay=today();return go(b.dataset.page);});
async function go(next,push=true){closeLessonSettings();if(['notes','library'].includes(next))next='materials';if(!me)return;if(root.dataset.page==='consent'&&await firstVisitConsent())return;if(fileView){fileView.dispose();fileView=null;}updateBack();root.dataset.page=next;if(push&&page!==next)history.push(page);if(history.length>50)history.shift();page=next;document.getElementById('status').textContent='';screen.replaceChildren();window.scrollTo(0,0);const host=node('section','fd-detail-page');screen.append(host);identity(host);
 document.querySelectorAll('#nav [data-page]').forEach(b=>b.setAttribute('aria-current',(b.dataset.page===page||(b.dataset.page==='ratings'&&['teacher','rating'].includes(page)))?'page':'false'));
 if(page==='comparison-settings')await comparisonSettingsPage(host).catch(fail);
 if(page==='history-points')await historyPointsPage(host).catch(fail);
 try{if(page==='admin-users')await adminUsersPage(host);if(page==='admin-channels')await adminChannelsPage(host);if(page==='study-group')await studyGroupPage(host);if(page==='import')await importSchedulePage(host);if(page==='calendar')calendar(host);if(page==='day'){await load();if(host.isConnected&&page==='day')day(host);}if(page==='lesson')await lesson(host);if(page==='teacher')await teacher(host);if(page==='library')await library(host);if(page==='documents')documentsPage(host);if(page==='profile'){profile(host);scheduleSource(host);if(me.source==='excel')host.append(button('Загрузить расписание',()=>go('import')));if(me.admin)await teacherPermissions(host);}if(page==='notes')notes(host);if(page==='materials')await materials(host);if(page==='deadlines')await deadlineList(host);if(page==='ratings')await ratingList(host);if(page==='rating')await ratingDetail(host);}catch(e){if(host.isConnected)fail(e);}if(push&&host.isConnected){const heading=host.querySelector('h1');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}}if(host.isConnected)maybeDiaryTour();}
function lessons(d){const source=days.find(x=>x.date===d);if(!source)return[];const result=[];
 for(const l of source.lessons){for(const p of l.periods){
 const rawTitle=p.disciplineFullName?.trim()||'Занятие';const key=[me.group,d,l.number,rawTitle,p.groups||p._diary_branch||''].join('|');
 result.push({key,schedule_id:p._diary_id,date:d,rawTitle,title:subjectTitle(p._diary_title||rawTitle),teacher:p.teachersNameFull||p.teachersName||'',teachers:teacherNames(p),start:p.timeStart,end:p.timeEnd,room:p.classroom||'',group:p.groups||'',subgroup:p._diary_subgroup_label||'',number:l.number,type:p.typeStr||'',_time_override:Boolean(p._time_override),_room_override:Boolean(p._room_override)});}}
 return result;}
function calendar(host){host.append(node('h1',null,'Календарь'));
 host.append(button('Принудительно обновить и вернуть удалённые пары',async()=>{await post('schedule/restore',{restore_deleted:true});await load();go('calendar',false);}),node('p','muted','Восстанавливает удалённые вами занятия. Личные добавленные пары и отключённые повторения сохраняются.'));
 const current=new Date(new Date().toLocaleDateString('sv-SE',{timeZone:'Europe/Moscow'})+'T12:00:00Z');
 const currentIndex=Math.max(2026*12+8,current.getUTCFullYear()*12+current.getUTCMonth());
 let month=new Date(Date.UTC(2026,8,1));const list=node('div');host.append(list);let currentBlock;
 function appendMonth(){const y=month.getUTCFullYear(),m=month.getUTCMonth(),block=node('section','fd-calendar-month');block.style.scrollMarginTop='85px';block.append(node('h2',null,month.toLocaleDateString(uiLocale(),{month:'long',year:'numeric',timeZone:'UTC'})));if(y*12+m===currentIndex)currentBlock=block;const grid=node('div','fd-month-grid');weekdays.forEach(w=>grid.append(node('span',null,w)));const offset=(month.getUTCDay()+6)%7;for(let i=0;i<offset;i++)grid.append(node('span'));
 for(let d=1;d<=new Date(Date.UTC(y,m+1,0)).getUTCDate();d++){const iso=new Date(Date.UTC(y,m,d)).toISOString().slice(0,10);grid.append(button(String(d),()=>changeDay(iso),'fd-date'+(iso===selectedDay?' today':'')));}block.append(grid);list.append(block);month=new Date(Date.UTC(y,m+1,1));}
 while(month.getUTCFullYear()*12+month.getUTCMonth()<=currentIndex+4)appendMonth();
 host.append(button('Следующие месяцы',appendMonth));
 if(currentIndex>2026*12+8)requestAnimationFrame(()=>{if(page==='calendar'&&currentBlock?.isConnected)currentBlock.scrollIntoView({block:'start'});});}
function day(host){host.classList.add('day-page');host.dayNavigation=buildDayNavigation(host);daySwipes(host,host.querySelector('.day-strip'));renderDayDetails(host.dayNavigation.details);}
function renderDayDetails(host){
 const override=content('schedule',me.group+'|'+selectedDay);if(override)host.append(node('p','schedule-clarification','Уточнение расписания:\n'+override));
 scheduleStatus(host);const list=lessons(selectedDay),extras=scheduleEvents.filter(event=>event.date===selectedDay);const sectionTitle=node('div','section-heading');sectionTitle.append(node('h2',null,'Расписание'));host.append(sectionTitle);if(!list.length&&!extras.length){const empty=node('div','empty-state');empty.append(icon('sun'),node('h2',null,me.source==='excel'&&!scheduleInfo.has_import?'Расписание ещё не загружено':!days.length&&scheduleInfo.syncing?'Загружаем расписание':'Свободный день'),node('p','muted',me.source==='excel'&&!scheduleInfo.has_import?(me.faculty==='fgp'?'Загрузите PDF своего расписания. Он превратится в привычные карточки занятий.':'Загрузите фото или файл своего расписания. Проверьте распознанные занятия и сохраните их.') :!days.length&&scheduleInfo.syncing?'Получаем занятия вашей группы из источника. Расписание появится автоматически.':'В сохранённом расписании на эту дату нет занятий.'));if(me.source==='excel'&&!scheduleInfo.has_import)empty.append(button('Загрузить расписание',()=>go('import'),'fd-primary schedule-upload'));host.append(empty);}
 [...list.map(lesson=>({lesson,start:lesson.start})),...extras.map(event=>({event,start:event.start}))].sort((a,b)=>String(a.start||'').localeCompare(String(b.start||''))).forEach(entry=>{if(entry.event){personalEventCard(host,{...entry.event,rawTitle:entry.event.title,title:subjectTitle(entry.event.title)});return;}const l=entry.lesson,card=node('article','fd-lesson-card');wholeLessonCard(card,()=>{selectedLesson=l;go('lesson');});lessonCardHeading(card,l);card.append(node('p','muted',(l.number?l.number+' пара · ':'')+l.start+'–'+l.end+(l.room?' · '+l.room:'')+(me.faculty==='geo'&&l.group?' · '+l.group:'')));lessonCardTitle(card,l);const homework=lessonHomework(l);if(homework.trim())card.append(node('p','homework-preview has-homework',homework));else card.classList.add('no-homework');lessonSettings(card,l);host.append(card);});if(me.faculty==='fgu'&&new Date(selectedDay+'T12:00:00Z').getUTCDay()===3)host.append(node('p','muted','Межфакультетский курс добавьте самостоятельно: выберите «Только я» и при необходимости еженедельное повторение.'));personalEventEditor(host);scheduleSource(host);if(me.source==='excel'&&!host.querySelector('.schedule-upload'))host.append(button('Загрузить расписание',()=>go('import')));}
function editor(host,label,kind,item){const details=node('details','fd-hw-editor');details.append(node('summary',null,label));const form=node('form'),input=node('textarea','fd-input fd-textarea');input.value=content(kind,item);input.maxLength=20000;input.setAttribute('aria-label',label);form.append(input);const submit=node('button','fd-primary',kind==='homework'||me.admin||!me.moderate?'Сохранить':'Отправить администратору');submit.type='submit';form.append(submit);const status=node('p','muted');status.setAttribute('role','status');form.append(status);
 form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{const r=await post('content',{kind,item,body:input.value});if(r.status==='approved'){contents=await api('content');await go(page,false);}else{status.textContent='Ожидает подтверждения администратора';details.open=true;}}catch(e){fail(e);}finally{submit.disabled=false;}};details.append(form);if(kind==='homework')details.dataset.homeworkEditor='';host.append(details);return details;}
async function fileSection(host,scope,item,provided){const list=node('div','fd-files');host.append(list);
 async function refresh(){const files=provided===undefined?await api('files?scope='+scope+'&item='+encodeURIComponent(item)):provided;provided=undefined;if(scope==='lesson'){const items=lessonFileItems(item);scheduleInfo.files=[...(scheduleInfo.files||[]).filter(file=>!items.includes(file.item)),...files.map(({id,scope,item,title,filename,size})=>({id,scope,item,title,filename,size}))];}list.replaceChildren();if(!files.length)list.append(node('p','muted','Файлов пока нет'));files.forEach(f=>list.append(fileDownloadRow(f)));}
 await refresh();const form=node('form','upload-form'),title=node('input','fd-input'),file=node('input','fd-input');title.placeholder='Название файла';title.setAttribute('aria-label','Название файла');file.type='file';file.required=true;file.setAttribute('aria-label','Прикрепить файл');const submit=node('button','fd-primary','Добавить файл');submit.type='submit';form.append(title,file,node('p','muted','Без подтверждения · до 100 МБ'),submit);host.append(form);
 attachUpload(form,{file,title,scope,item,submit,refresh:async()=>{await refresh();if(page==='materials')await go('materials',false);}});}
async function lesson(host){
 const l=selectedLesson;if(!l)return go('day',false);const detail=api('lesson-detail?item='+encodeURIComponent(l.key)),header=node('div','lesson-detail-header');
 lessonSettings(header,l);header.append(lessonBadge(l.type),node('h1',null,l.title),node('p','muted',dateLabel(l.date)+' · '+l.start+'–'+l.end));teacherLinks(header,l,true);if(l.type!=='event')header.append(button('Изменить преподавателей',()=>editSubjectTeachers(l),'fd-secondary lesson-teacher-edit'));host.append(header,node('h2',null,'Домашнее задание'),lessonHomework(l)?userText('p',null,lessonHomework(l)):node('p',null,'Пока не записано'));
 const homeworkEditor=editor(host,'Записать или изменить ДЗ','homework',l.key);homeworkEditor.querySelector('textarea').value=lessonHomework(l);if(l.source==='custom'&&l.visibility==='personal'&&l.can_delete)personalEventEditor(host,await api('schedule/custom/'+l.id));host.append(node('h2',null,'Конспекты и выполненные домашние задания'));const data=await detail;if(!host.isConnected)return;await fileSection(host,'lesson',l.key,data.files);await deadlineEditor(host,l,data.deadline);
}
async function teacher(host){host.append(button('★ Рейтинг и отзывы',()=>go('rating')));const photos=await api('teacher-photos');const normalize=s=>s.toLocaleLowerCase('ru').replaceAll('ё','е').trim().replace(/\s+/g,' ');const match=Object.keys(photos).find(name=>normalize(name)===normalize(selectedTeacher));const placeholder=node('div','fd-photo-placeholder',selectedTeacher.split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('')||'—');placeholder.setAttribute('aria-label','Фотография отсутствует');if(match){const img=node('img','fd-portrait');img.src=photos[match];img.alt=selectedTeacher;img.dataset.personName='';img.style.cssText='width:146px;height:173px;object-fit:cover;margin:0 auto 20px;border-radius:14px';img.onerror=()=>img.replaceWith(placeholder);host.append(img);}else host.append(placeholder);host.append(node('h1',null,selectedTeacher||'Преподаватель'),node('h2',null,'Личная характеристика'));if(selectedTeacher){privateEditor(host,'teacher',selectedTeacher,'Мои записи о преподавателе');host.append(node('p','muted','Эта характеристика появится только в ваших напоминаниях. Настройка в боте: /notifications'));sharedTeacher(host,selectedTeacher);}}
async function library(host){host.append(node('h1',null,'Литература'));topics=await api('topics');const select=node('select','fd-input');select.setAttribute('aria-label','Тема литературы');topics.forEach(t=>{const o=node('option',null,t.title);o.value=t.id;select.append(o);});host.append(select);const files=node('div');host.append(files);const draw=async()=>{const panel=node('div');files.replaceChildren(panel);if(select.value)await fileSection(panel,'literature',select.value);};select.onchange=()=>draw().catch(fail);await draw();if(me.admin){const form=node('form'),input=node('input','fd-input');input.required=true;input.placeholder='Название новой темы';input.setAttribute('aria-label','Новая тема');const submit=node('button','fd-primary','Создать тему');form.append(input,submit);form.onsubmit=async e=>{e.preventDefault();try{await post('topics',{title:input.value});await go('library',false);}catch(e){fail(e);}};host.append(node('h2',null,'Новая тема'),form);}}
function profile(host){
 renderProfile(host);
}
let lastLoadAt=0,lastLoadedDay='',loadJob=null,eventsFirst='',eventsLast='';
async function load(force=false){
 const generation=loginGeneration;
 while(loadJob){await loadJob;if(generation!==loginGeneration||!me)return;}
 if(!force&&selectedDay>=eventsFirst&&selectedDay<=eventsLast&&Date.now()-lastLoadAt<30000)return;
 const date=selectedDay,first=addDays(date,-60),last=addDays(date,60),pointsVersion=historyPointRevision;
 const job=(async()=>{const result=await Promise.all([api('schedule'),api('content'),api('personal'),api('schedule/events?start='+first+'&end='+last),api('history-points/summary')]);if(!me||generation!==loginGeneration)return;[scheduleInfo,contents,personal,scheduleEvents]=result;if(pointsVersion===historyPointRevision){historyPointTotals=result[4].totals;historyPointTotal=result[4].total;}eventsFirst=first;eventsLast=last;days=scheduleInfo.days;if(me){me.group=scheduleInfo.group;me.group_id=scheduleInfo.group_id||me.group_id;me.source=scheduleInfo.source||me.source;if(scheduleInfo.faculty&&me.faculty!==scheduleInfo.faculty){me.faculty=scheduleInfo.faculty;universityBrand(me.faculty);}}lastLoadedDay=date;lastLoadAt=Date.now();})();
 loadJob=job;try{await job;}finally{if(loadJob===job)loadJob=null;}
}
let loginGeneration=0;
function manualLogin(){try{return sessionStorage.getItem('fgu-logged-out')==='1';}catch{return false;}}
function rememberLogout(value){try{if(value)sessionStorage.setItem('fgu-logged-out','1');else sessionStorage.removeItem('fgu-logged-out');}catch{}}
async function boot(code=''){
 if(typeof historyPointsPage==='undefined')await Promise.all([
  new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/static/history-points.js?v=20261009-points-simple-1';script.onload=resolve;script.onerror=()=>reject(Error('Обновите страницу, чтобы загрузить интерфейс.'));document.head.append(script);}),
  new Promise((resolve,reject)=>{const style=document.createElement('link');style.rel='stylesheet';style.href='/static/history-points.css?v=20261009-points-simple-1';style.onload=resolve;style.onerror=()=>reject(Error('Обновите страницу, чтобы загрузить оформление.'));document.head.append(style);})
 ]);
 wireHistoryNavigation();
 // A cached previous HTML page can receive refreshed scripts from the edge.
 // Load the matching day controls before displaying any authenticated page.
 if(typeof buildDayNavigation==='undefined')await Promise.all([
  new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/static/day-navigation.js?v=20261009-comparison-2';script.onload=resolve;script.onerror=()=>reject(Error('Обновите страницу, чтобы загрузить интерфейс.'));document.head.append(script);}),
  new Promise((resolve,reject)=>{const style=document.createElement('link');style.rel='stylesheet';style.href='/static/navigation.css?v=20261009-comparison-2';style.onload=resolve;style.onerror=()=>reject(Error('Обновите страницу, чтобы загрузить оформление.'));document.head.append(style);})
 ]);
 if(typeof comparisonSettingsPage==='undefined')await Promise.all([
  new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/static/group-comparison.js?v=20261009-points-simple-1';script.onload=resolve;script.onerror=()=>reject(Error('Обновите страницу, чтобы загрузить интерфейс.'));document.head.append(script);}),
  new Promise((resolve,reject)=>{const style=document.createElement('link');style.rel='stylesheet';style.href='/static/group-comparison.css?v=20261009-points-simple-1';style.onload=resolve;style.onerror=()=>reject(Error('Обновите страницу, чтобы загрузить оформление.'));document.head.append(style);})
 ]);
 if(manualLogin()){await browserLogin(false);return;}
 if(tg?.initData){
  try{const result=await post('auth',{initData:tg.initData});if(!result.needs_code){await enterBrowser(result);return;}}catch(error){if(error.status!==401)fail(error);}
 }
 if(inMax()){
  try{const result=await post('max/auth',{initData:maxInitData()});if(!result.needs_code){await enterBrowser(result);confirmMaxBrowserRequest(result);return;}}catch(error){fail(error);}
  await browserLogin(false);return;
 }
 try{const existing=await api('me');await enterBrowser(existing);return;}catch(e){if(e.status!==401&&e.status!==403)fail(e);}
 
 await browserLogin(false);
}
async function telegramLogin(code=''){
 const r=await post('auth',{initData:tg.initData,code});
 if(r.needs_code){await browserLogin(false);fail(Error('Завершите регистрацию в боте по приглашению или разрешению администратора.'));return;}
 await enterBrowser(r);
}
async function logout(){
 const control=document.getElementById('logout');control.disabled=true;
 try{
  const feedback=matchMedia('(prefers-reduced-motion: reduce)').matches?Promise.resolve():new Promise(resolve=>setTimeout(resolve,450));
  await Promise.all([post('logout',{push_device:await currentPushDevice()}),feedback]);releaseBrowserPush();rememberLogout(true);loginGeneration++;
  for(const transfer of activeUploads)transfer.abort();
  if(fileView){fileView.dispose();fileView=null;}
  lastLoadAt=0;lastLoadedDay='';eventsFirst=eventsLast='';me=undefined;csrf='';days=[];contents=[];personal=[];topics=[];scheduleEvents=[];scheduleInfo={};history=[];historyPointTotals=[];historyPointTotal=0;historyPointTerm=historyPointSeed='';historyPointAdding=false;historyPointRevision++;selectedLesson=undefined;selectedTeacher='';
  document.getElementById('nav').hidden=true;document.getElementById('status').textContent='';updateBack();
  await browserLogin(false);window.scrollTo(0,0);
 }finally{control.disabled=false;}
}
document.getElementById('logout').onclick=()=>logout().catch(fail);
async function enterBrowser(result){rememberLogout(false);loginGeneration++;csrf=result.csrf;me=await api('me');try{if(!localStorage.getItem('midiary-language'))setUiLanguage(me.language||'ru');else if(me.language!==uiLanguage())await post('language',{language:uiLanguage()});}catch{}if(me.theme)theme(me.theme);csrf=me.csrf;universityBrand(me.faculty);if(await firstVisitConsent())return;if(me.needs_group||me.choose_study_group||(chosenFaculty&&chosenFaculty!==me.faculty)){await go('study-group',false);return;}const launch=pushLaunchTarget();selectedDay=launch.date||today();try{await load();}catch(e){me=undefined;updateBack();throw e;}document.getElementById('nav').hidden=false;await go(launch.view,false);window.history.replaceState({},'',location.pathname);}
async function browserLogin(restore=true){
 if(restore)try{await enterBrowser(await api('me'));return;}catch(e){if(e.status!==401&&e.status!==403)fail(e);}
 document.getElementById('nav').hidden=true;updateBack();root.dataset.page='login';screen.replaceChildren();
 const host=node('section','fd-detail-page login-page'),logo=node('img','midiary-mark');logo.src='/static/midiary-logo.svg';logo.alt='Midiary';
 host.append(logo,node('h1',null,'Midiary'),node('p','login-intro','Всё для учёбы. В одном месте. Войдите через Telegram, MAX или по коду. Регистрация — по приглашению администратора.'));host.append(languagePicker());
 const form=node('form'),input=inputField(form,'Код доступа','password');input.autocomplete='current-password';input.required=true;input.id='login-code';
 const save=node('button','fd-primary','Войти');save.type='submit';form.append(save);form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await enterBrowser(await post('browser/id',{code:input.value.trim(),...(maxInitData()?{maxInitData:maxInitData()}:{})}));}catch(e){fail(e);}finally{save.disabled=false;}};
 host.append(form);form.before(button('Войти через Telegram',()=>beginTelegramLogin(host),'fd-primary telegram-login'),button('Войти через MAX',()=>beginMaxLogin(host),'fd-primary max-login'));
 const register=node('section','bot-registration');register.append(node('h2',null,'Регистрация через бота'),node('p','muted','Регистрация — по коду администратора или его разрешению для вашего Telegram ID. После регистрации выберите факультет и группу в дневнике. Для ФИЯР и ФГП загрузите своё расписание. Существующий аккаунт MAX можно связать по Telegram ID с подтверждением в Telegram.'),button('Регистрация через Telegram',()=>beginBotRegistration('telegram')),button('Регистрация через MAX',()=>beginBotRegistration('max')));host.append(register);screen.append(host);resumeMessengerLogin(host);
}
try{tg?.ready();tg?.expand();}catch{}try{theme(document.documentElement.dataset.fguTheme||'dark');}catch{theme(document.documentElement.dataset.fguTheme||'dark');}boot().catch(fail);
setInterval(async()=>{if(!me||me.needs_group||['study-group','consent'].includes(page)||refreshInFlight||document.hidden||root.querySelector('dialog[open]'))return;refreshInFlight=true;try{const editing=!!screen.querySelector('form[data-dirty="true"],details[open]')||['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName);const before=JSON.stringify([days,contents,scheduleEvents,scheduleInfo.files,scheduleInfo.syncing,scheduleInfo.error]);await load(true);if(!editing&&['day','calendar','profile'].includes(page)&&before!==JSON.stringify([days,contents,scheduleEvents,scheduleInfo.files,scheduleInfo.syncing,scheduleInfo.error])&&!screen.querySelector('form[data-dirty="true"],details[open]')&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)){const y=window.scrollY;if(page==='day')refreshDayView();else await go(page,false);window.scrollTo(0,y);}}catch{}finally{refreshInFlight=false;}},15000);

async function reminderSettings(host){
 const section=node('section','lesson-reminders'),status=node('p','muted');status.setAttribute('role','status');section.append(node('h2',null,'Напоминания о парах'),status);host.append(section);
 try{const prefs=await api('reminders');if(!host.isConnected)return;const fields=offsetPicker(section,'Когда напоминать о парах',prefs.choices,prefs.offsets);const save=button('Сохранить',async()=>{await post('reminders',{offsets:fields.values()});status.textContent='Настройки сохранены.';});section.append(save);status.textContent=prefs.linked?'Можно выбрать несколько интервалов. Уведомления приходят в подключённые Telegram и MAX.':'Привяжите Telegram или MAX командой /link и своим кодом доступа.';}catch(error){status.textContent=error.message;}
}
