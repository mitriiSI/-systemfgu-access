// Shared vector icons keep controls consistent across browsers and WebViews.
const iconPaths = {"back": "<path d=\"m12 5-7 7 7 7M5 12h15\"/>", "chevron-left": "<path d=\"m14 6-6 6 6 6\"/>", "chevron-right": "<path d=\"m10 6 6 6-6 6\"/>", "sun": "<circle cx=\"12\" cy=\"12\" r=\"4\"/><path d=\"M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5\"/>", "moon": "<path d=\"M20.5 14A8.6 8.6 0 0 1 10 3.5 8.6 8.6 0 1 0 20.5 14Z\"/>", "calendar": "<rect x=\"3\" y=\"5\" width=\"18\" height=\"16\" rx=\"4\"/><path d=\"M7 3v4m10-4v4M3 10h18M7 14h2m3 0h2m3 0h.01M7 17h2m3 0h2\"/>", "notes": "<rect x=\"4\" y=\"3\" width=\"16\" height=\"18\" rx=\"4\"/><path d=\"M8 8h8M8 12h8m-8 4h5\"/>", "folder": "<path d=\"M3 8V6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8Z\"/>", "more": "<circle cx=\"5\" cy=\"12\" r=\"1\"/><circle cx=\"12\" cy=\"12\" r=\"1\"/><circle cx=\"19\" cy=\"12\" r=\"1\"/>"};
function icon(name){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
 svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');
 svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');
 svg.innerHTML=iconPaths[name]||iconPaths.more;
 if(name==='sun'){svg.querySelector('path')?.classList.add('icon-sun-rays');svg.querySelector('circle')?.classList.add('icon-sun-disc');}
 if(name==='moon')svg.querySelector('path')?.classList.add('icon-moon');
 return svg;
}
function iconButton(name,label,action){const b=button('',action,'fd-icon-button');b.setAttribute('aria-label',label);b.title=label;b.append(icon(name));return b;}
function lessonBadge(type){
 const value=String(type).toLowerCase();
 const kind=value.includes('lec')||value.includes('лек')?'lecture':value.includes('sem')||value.includes('сем')?'seminar':value.includes('prac')||value.includes('прак')?'practice':'other';
 return node('span','lesson-badge '+kind,({lecture:'Лекция',seminar:'Семинар',practice:'Практика'})[kind]||type||'Занятие');
}
function sharedTeacher(host,item){
 const section=node('section','shared-teacher'),form=node('form'),input=node('textarea','fd-input fd-textarea');
 input.value=content('teacher_notice',item);input.maxLength=20000;input.setAttribute('aria-label','Общая характеристика преподавателя');
 section.append(node('h2',null,'Общая характеристика'),node('p','muted','Видно всем участникам'));
 input.readOnly=!me.teacher_write;form.append(input);
 if(me.teacher_write){const save=node('button','fd-primary','Сохранить общую характеристику');save.type='submit';form.append(save);const status=node('p','muted');form.append(status);
 form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await post('content',{kind:'teacher_notice',item,body:input.value});contents=await api('content');status.textContent='Сохранено для всех';}catch(e){fail(e);}finally{save.disabled=false;}};
 }else form.append(node('p','muted','Администратор отключил для вас изменение общих характеристик.'));
 section.append(form);host.append(section);
}
async function teacherPermissions(host){
 const section=node('details');section.append(node('summary',null,'Права на общие характеристики'));
 const members=await api('teacher-permissions');
 members.forEach(member=>{const label=node('label','permission-row'),check=node('input');check.type='checkbox';check.checked=member.allowed;
 check.onchange=async()=>{check.disabled=true;try{await post('teacher-permissions',{code:member.code,allowed:check.checked});}catch(e){check.checked=!check.checked;fail(e);}finally{check.disabled=false;}};
 label.append(check,node('span',null,member.name+' — разрешить редактировать'));section.append(label);});host.append(section);
}
function notes(host){
 host.append(node('h1',null,'Мои заметки'));
 const shell=node('div','notes-shell'),list=node('aside','notes-list'),area=node('section','notes-editor');shell.append(list,area);host.append(shell);
 function data(record){try{const parsed=JSON.parse(record.body);if(parsed&&typeof parsed==='object'&&!Array.isArray(parsed))return {title:typeof parsed.title==='string'?parsed.title:'Заметка',text:typeof parsed.text==='string'?parsed.text:record.body};}catch{}return {title:'Заметка',text:record.body};}
 function drawList(){list.replaceChildren(button('＋ Новая заметка',()=>edit(null)));const records=personal.filter(x=>x.kind==='note'&&!x.item.startsWith('reader-bookmark:'));
 if(!records.length)list.append(node('p','muted','Заметок пока нет'));
 records.forEach(record=>{const d=data(record),entry=button('',()=>edit(record),'note-preview');entry.append(node('strong',null,d.title||'Заметка'),node('span','muted',new Date(record.updated).toLocaleString(uiLocale())),node('span',null,(d.text||'').slice(0,90)||'Нет текста'));list.append(entry);});}
 function edit(record){shell.classList.add('editing');area.replaceChildren();const back=button('‹ Все заметки',()=>{shell.classList.remove('editing');area.replaceChildren(node('p','muted','Выберите заметку'));},'notes-back');area.append(back);
 const d=record?data(record):{title:'',text:''},form=node('form','fd-note-form'),title=node('input','fd-input'),body=node('textarea','fd-input note-body');
 title.value=d.title||'';title.placeholder='Название';title.required=true;title.maxLength=200;title.setAttribute('aria-label','Название заметки');body.value=d.text||'';body.maxLength=18000;body.placeholder='Текст заметки';body.setAttribute('aria-label','Текст заметки');
 const stamp=node('p','muted',record?'Изменено: '+new Date(record.updated).toLocaleString(uiLocale()):'Новая заметка · видна только вам');const save=node('button','fd-primary','Сохранить');save.type='submit';form.append(stamp,title,body,save);area.append(form);
 let item=record?.item||readerUuid();
 form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await post('personal',{kind:'note',item,body:JSON.stringify({title:title.value,text:body.value})});personal=await api('personal');stamp.textContent='Изменено: '+new Date(personal.find(x=>x.kind==='note'&&x.item===item).updated).toLocaleString(uiLocale());delete form.dataset.dirty;drawList();}catch(e){fail(e);}finally{save.disabled=false;}};
 area.append(button('Удалить',async()=>{if(!confirm('Удалить заметку?'))return;await post('personal',{kind:'note',item,delete:true});personal=await api('personal');drawList();shell.classList.remove('editing');area.replaceChildren(node('p','muted','Выберите заметку'));}));
 }
 drawList();area.append(node('p','muted','Выберите заметку слева или создайте новую.'));
}
const reminderTimes=[[0,'Не напоминать'],[15,'За 15 минут'],[60,'За час'],[180,'За 3 часа'],[1440,'За сутки'],[2880,'За 2 суток']];
function deadlineReminder(host,record){const section=node('section');host.append(section);const fields=offsetPicker(section,'Мои напоминания в Telegram и MAX',[0,15,60,180,1440,2880],record.offsets||[]);section.append(button('Сохранить',async()=>{await post('deadlines/reminder',{item:record.item,offsets:fields.values()});readerStatus('Настройки сохранены.');}));}
async function deadlineEditor(host,lesson,provided){
 const section=node('section','lesson-deadline');let record=provided===undefined?(await api('deadlines')).find(x=>x.item===lesson.key):provided;const item=record?.item||lesson.key;section.append(node('h2',null,'Дедлайн ДЗ'));
 const form=node('form'),input=node('input','fd-input');input.type='datetime-local';input.required=true;input.setAttribute('aria-label','Срок сдачи ДЗ по Москве');
 if(record)input.value=record.due.slice(0,16);const save=node('button','fd-primary','Сохранить срок');save.type='submit';form.append(node('p','muted','Общий срок сдачи · московское время'),input,save);section.append(form);
 form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await post('deadlines',{item,title:lesson.title,due:input.value+':00+03:00'});await go('lesson',false);}catch(e){fail(e);}finally{save.disabled=false;}};
 if(record){deadlineReminder(section,record);if(me.admin)section.append(button('Убрать дедлайн',async()=>{if(!confirm('Убрать общий дедлайн и его напоминания?'))return;await post('deadlines',{item,delete:true});await go('lesson',false);}));}host.append(section);
}
async function deadlineList(host){
 host.append(node('h1',null,'Дедлайны ДЗ'));const rows=await api('deadlines'),now=Date.now(),near=now+7*86400000;
 if(!rows.length){host.append(node('p',null,'Добавьте срок сдачи в карточке пары.'));return;}
 for(const [key,label,predicate] of [['near','Близкие · ближайшие 7 дней',x=>x>=now&&x<=near],['far','Далёкие · позже 7 дней',x=>x>near],['past','Прошедшие',x=>x<now]]){
  const section=node('section','deadline-group');section.dataset.period=key;section.append(node('h2',null,label));host.append(section);
  const selected=rows.filter(r=>predicate(Date.parse(r.due))).sort((a,b)=>key==='past'?Date.parse(b.due)-Date.parse(a.due):Date.parse(a.due)-Date.parse(b.due));
  if(!selected.length)section.append(node('p','muted','Дедлайнов нет'));
  for(const record of selected){const box=node('article','fd-lesson-card');box.append(node('h3',null,record.title),node('p',null,'Сдать до '+new Date(record.due).toLocaleString(uiLocale(),{timeZone:'Europe/Moscow'})+' (МСК)'));
   if(key==='past')box.append(node('p','muted','Срок прошёл'));else{const reminders=node('details','fd-hw-editor');reminders.append(node('summary',null,'Напоминания'));box.append(reminders);deadlineReminder(reminders,record);}
   if(me.admin)box.append(button('Удалить дедлайн',async()=>{if(!confirm('Убрать общий дедлайн и его напоминания?'))return;await post('deadlines',{item:record.item,delete:true});await go('deadlines',false);}));section.append(box);
  }
 }
}
let materialCategory='notes';
async function collectionMaterials(host){
 host.append(node('h1',null,'Материалы'));const categories={notes:'Конспекты',homework:'ДЗ',presentations:'Презентации',projects:'Проекты'},sets=await api('material-sets');
 const tabs=node('div','material-tabs'),list=node('div'),detail=node('section');let category=materialCategory;host.append(tabs,list,detail);
 async function open(set){const panel=node('section');detail.replaceChildren(panel);panel.append(node('h2',null,set.title),node('p','muted',set.subject+' · '+categories[set.category]));await fileSection(panel,'material',String(set.id));
 const others=sets.filter(x=>x.id!==set.id&&x.subject===set.subject&&x.category===set.category);if(me.admin&&others.length){const select=node('select','fd-input');select.setAttribute('aria-label','Объединить подборки');others.forEach(x=>{const option=node('option',null,x.title);option.value=x.id;select.append(option);});panel.append(node('h2',null,'Объединить с другой подборкой'),select,button('Перенести сюда все файлы выбранной подборки',async()=>{if(!confirm('Перенести все файлы и убрать выбранную подборку?'))return;await post('material-sets/merge',{source:Number(select.value),target:set.id});await go('materials',false);}));}}
 function draw(){tabs.replaceChildren();Object.entries(categories).forEach(([key,title])=>tabs.append(button(title,()=>{category=key;materialCategory=key;detail.replaceChildren();draw();},key===category?'fd-primary':'fd-secondary')));list.replaceChildren();
 const filtered=sets.filter(x=>x.category===category);[...new Set(filtered.map(x=>x.subject))].forEach(subject=>{list.append(node('h2',null,subject));filtered.filter(x=>x.subject===subject).forEach(x=>list.append(button(x.title,()=>open(x))));});
 const form=node('form'),subject=node('input','fd-input'),title=node('input','fd-input');subject.placeholder='Предмет';subject.required=true;subject.maxLength=200;subject.setAttribute('aria-label','Предмет подборки');title.placeholder='Название подборки';title.required=true;title.maxLength=200;title.setAttribute('aria-label','Название подборки');const save=node('button','fd-primary','Создать подборку');save.type='submit';form.append(node('h2',null,'Новая подборка: '+categories[category]),subject,title,save);
 form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await post('material-sets',{subject:subject.value,title:title.value,category});await go('materials',false);}catch(e){fail(e);}finally{save.disabled=false;}};list.append(form);
 }
 draw();
}

iconPaths.forward = '<path d="m12 5 7 7-7 7M19 12H4"/>';

function eventEditor(host){
 const details=node('details','fd-hw-editor event-editor');details.append(node('summary',null,'Добавить пару или событие'));
 const form=node('form','event-form'),fields={};
 function field(name,title,type='text',required=false,maxLength=200){
  const label=node('label','fd-label',title),input=node(type==='textarea'?'textarea':'input','fd-input');
  if(type!=='textarea')input.type=type;input.required=required;input.maxLength=maxLength;input.name=name;input.setAttribute('aria-label',title);label.append(input);form.append(label);fields[name]=input;return input;
 }
 const typeLabel=node('label','fd-label','Что добавить'),type=node('select','fd-input');type.name='type';type.setAttribute('aria-label','Что добавить');
 for(const [value,title] of [['lesson','Дополнительная пара'],['event','Событие']]){const option=node('option',null,title);option.value=value;type.append(option);}typeLabel.append(type);form.append(typeLabel);fields.type=type;
 field('title','Название','text',true);field('date','Дата','date',true).value=selectedDay;
 field('start','Начало (МСК)','time',true);field('end','Окончание (МСК)','time');field('room','Место или аудитория','text',false,120);
 const teachers=teacherFields(form);type.onchange=()=>{teachers.element.hidden=type.value!=='lesson';};
 field('description','Описание','textarea',false,2000);
 const status=node('p','muted');status.setAttribute('role','status');const save=node('button','fd-primary',me.moderate&&!me.admin?'Отправить администратору':'Добавить в расписание');save.type='submit';
 form.append(node('p','muted','Видно всей группе. Обновление расписания ФГУ сохранит эту запись.'),save,status);
 form.onsubmit=async e=>{e.preventDefault();const body=Object.fromEntries(Object.entries(fields).map(([key,input])=>[key,input.value]));body.teachers=teachers.values();
  if(body.end&&body.end<=body.start){status.textContent='Окончание должно быть позже начала.';return;}
  save.disabled=true;try{const result=await post('schedule/events',body);if(result.status==='pending'){status.textContent='Отправлено администратору на подтверждение';form.reset();teachers.reset();fields.date.value=selectedDay;delete form.dataset.dirty;}else{selectedDay=body.date;await load(true);await go('day',false);}}catch(error){status.textContent=error.message;}finally{save.disabled=false;}
 };details.append(form);host.append(details);
}
function eventCard(host,event){
 const card=node('article','fd-lesson-card event-card');
 card.append(lessonBadge(event.type==='lesson'?'Дополнительная пара':'Событие'),node('p','muted',(event.number?event.number+' пара · ':'')+event.start+(event.end?'–'+event.end:'')+' · МСК'+(event.room?' · '+event.room:'')));
 const key=[me.group,event.date,'extra',event.id].join('|');wholeLessonCard(card,()=>{selectedLesson={...event,key};go('lesson');});
 if(event.type==='lesson'){
  card.append(button(event.title,()=>{selectedLesson={...event,key};go('lesson');},'fd-lesson-name'));
  teacherLinks(card,event);
 }else card.append(node('h2','event-title',event.title));
 if(event.description)card.append(node('p','event-description',event.description));
 lessonSettings(card,{...event,source:event.source||'shared'});
 host.append(card);
}

async function hideLesson(lesson){
 await post('schedule/hide',{id:lesson.occurrence_id||lesson.schedule_id,date:lesson.date});await load(true);await go('day',false);
}
function personalEventEditor(host,initial=null){
 const details=node('details','fd-hw-editor event-editor');details.append(node('summary',null,initial?'Изменить свою пару или событие':'Добавить свою пару или событие'));
 const form=node('form','event-form'),fields={};
 function field(key,title,type='text',required=false,max=200){const label=node('label','fd-label',title),input=node(type==='textarea'?'textarea':'input','fd-input');if(type!=='textarea')input.type=type;input.required=required;input.maxLength=max;input.setAttribute('aria-label',title);fields[key]=input;label.append(input);form.append(label);return input;}
 function select(key,title,options){const label=node('label','fd-label',title),input=node('select','fd-input');input.setAttribute('aria-label',title);for(const [value,text] of options){const option=node('option',null,text);option.value=value;input.append(option);}fields[key]=input;label.append(input);form.append(label);return input;}
 select('type','Что добавить',[['lesson','Пара'],['event','Событие']]);select('number','Номер пары',[['0','Без номера'],...Array.from({length:12},(_,i)=>[String(i+1),String(i+1)+' пара'])]);field('title','Название','text',true);field('date','Дата первого занятия','date',true).value=selectedDay;
 select('recurrence','Повторение',[['once','Только в эту дату'],['weekly','Каждую неделю в этот день']]);
 select('visibility','Кто увидит',[['personal','Только я'],...(me.admin?[['group','Вся группа']]:[])]);
 field('start','Начало (МСК)','time',true);field('end','Окончание (МСК)','time');const teachers=teacherFields(form,teacherNames(initial));field('room','Аудитория или место','text',false,120);field('description','Описание','textarea',false,2000);
 if(initial)for(const [key,input] of Object.entries(fields))input.value=String(initial[key]??'');
 const status=node('p','muted');status.setAttribute('role','status');const save=node('button','fd-primary',initial?'Сохранить изменения':'Добавить');save.type='submit';form.append(node('p','muted','Личные занятия не меняют расписание остальных. Еженедельное занятие повторяется с выбранной даты, пока вы его не отключите.'),save,status);
 form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{const b=Object.fromEntries(Object.entries(fields).map(([key,input])=>[key,input.value]));if(initial)b.id=initial.id;b.number=Number(b.number);b.teachers=teachers.values();await post('schedule/custom',b);selectedDay=b.date;await load(true);await go('day',false);}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};details.append(form);host.append(details);return details;
}
function personalEventCard(host,event){
 const card=node('article','fd-lesson-card event-card'),badge=event._schedule_import?(event.lesson_type||'Пара'):event.recurrence==='weekly'?'Каждую неделю':event.type==='lesson'?'Дополнительная пара':'Событие';
 const key=[me.group,event.date,'extra',event.id].join('|');wholeLessonCard(card,()=>{selectedLesson={...event,key};go('lesson');});
 const lesson={...event,key};lessonCardHeading(card,lesson,badge);card.append(node('p','muted',(event.number?event.number+' пара · ':'')+event.start+(event.end?'–'+event.end:'')+' · '+(event.visibility==='personal'?'Только у меня':'Общее расписание')));lessonCardTitle(card,lesson);card.classList.add('no-homework');
 if(event.room)card.append(node('p','muted',event.room));if(event.description)card.append(node('p',null,event.description));
 const homework=content('homework',key);if(homework.trim()){card.classList.remove('no-homework');card.append(node('p','homework-preview has-homework',homework));}
 lessonSettings(card,lesson);
 host.append(card);
}
const ratingCriteria=[['clarity','Понятность'],['knowledge','Компетентность'],['communication','Коммуникация']];
function ratingScore(value){return value==null?'Нет оценок':Number(value).toFixed(1);}
function teacherInitials(name){return name.split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('');}
async function ratingList(host){
 host.append(node('h1',null,'Рейтинг преподавателей'));
 const search=node('input','fd-input'),sort=node('select','fd-input'),rated=node('input'),filter=node('label','rating-filter'),list=node('div','rating-list'),summary=node('p','muted');
 search.placeholder='Поиск по имени…';search.setAttribute('aria-label','Поиск преподавателя');sort.setAttribute('aria-label','Сортировка рейтинга');
 for(const [value,label] of [['score','По убыванию рейтинга'],['low','По возрастанию рейтинга'],['count','По числу отзывов'],['name','По имени']]){const option=node('option',null,label);option.value=value;sort.append(option);}
 rated.type='checkbox';filter.append(rated,node('span',null,'Только с отзывами'));host.append(search,sort,filter,summary,list);const rows=await api('teacher-ratings');
 function draw(){const shown=rows.filter(row=>row.teacher.toLocaleLowerCase('ru').includes(search.value.trim().toLocaleLowerCase('ru'))&&(!rated.checked||row.count));shown.sort((a,b)=>sort.value==='name'?a.teacher.localeCompare(b.teacher,'ru'):((a.score==null)-(b.score==null))||(sort.value==='count'?b.count-a.count:sort.value==='low'?a.score-b.score:b.score-a.score)||a.teacher.localeCompare(b.teacher,'ru'));summary.textContent='Преподавателей: '+shown.length;list.replaceChildren();
  if(!shown.length)list.append(node('p','muted','Преподаватели не найдены.'));
  shown.forEach((row,i)=>{const card=button('',()=>{selectedTeacher=row.teacher;go('rating');},'rating-card'),avatar=node('span','rating-avatar',teacherInitials(row.teacher)),body=node('span','rating-card-body'),stats=node('span','rating-card-stats');body.append(personNameNode(row.teacher),node('span','rating-stars',(row.count?'★ ':'')+ratingScore(row.score)));stats.append(node('span',null,row.count+' отзывов'),node('span','rating-recommend',row.recommended==null?'':Math.round(row.recommended)+'% рекомендуют'));card.append(node('span','rating-rank',String(i+1)),avatar,body,stats);list.append(card);});
 }
 search.oninput=draw;sort.onchange=draw;rated.onchange=draw;draw();
}
async function ratingDetail(host){
 const name=selectedTeacher;host.append(button('← Все преподаватели',()=>go('ratings')),node('h1',null,name));
 const [ratings,reviews]=await Promise.all([api('teacher-ratings'),api('teacher-reviews?teacher='+encodeURIComponent(name))]);const rating=ratings.find(row=>row.teacher===name)||{count:0},overview=node('section','rating-overview');
 overview.append(node('span','rating-avatar',teacherInitials(name)),node('h2',null,name),node('p','rating-stars','★ '+ratingScore(rating.score)),node('p','muted',rating.count+' отзывов'+(rating.recommended!=null?' · '+Math.round(rating.recommended)+'% рекомендуют':'')));
 for(const [key,label] of ratingCriteria){const row=node('div','rating-metric'),bar=node('meter');bar.min=0;bar.max=5;bar.value=rating[key]||0;bar.setAttribute('aria-label',label);row.append(node('span',null,label),bar,node('strong',null,rating[key]==null?'—':ratingScore(rating[key])));overview.append(row);}host.append(overview,node('h2',null,'Отзывы'),node('p','muted','Отзывы отражают личный опыт участников. Оценки рассчитаны по опубликованным отзывам и не подтверждены университетом. Комментарии видны участникам выбранного факультета.'));
 const list=node('div','review-list');host.append(list);if(!reviews.length)list.append(node('p','muted','Отзывов пока нет. Вы можете оставить первый.'));
 for(const review of reviews){const card=node('article','review-card');card.append(personNameNode(review.author),node('span',review.recommend?'rating-recommend':'muted',review.recommend?'Рекомендует':'Не рекомендует'),node('p','muted',new Date(review.updated).toLocaleDateString(uiLocale())));
  for(const [key,label] of ratingCriteria)card.append(node('p','review-criterion',label+' · '+'★'.repeat(review[key])+'☆'.repeat(5-review[key])));
  if(review.comment)card.append(node('p','review-comment',review.comment));if(review.can_delete)card.append(button(review.mine?'Удалить мой отзыв':'Удалить отзыв',async()=>{await post('teacher-reviews',{id:review.id,delete:true});await go('rating',false);}));list.append(card);
 }
 const mine=reviews.find(review=>review.mine),form=node('form','review-form'),values={};form.append(node('h2',null,mine?'Изменить мой отзыв':'Оставить отзыв'));
 for(const [key,label] of ratingCriteria){const group=node('fieldset','review-stars');group.append(node('legend',null,label));for(let score=1;score<=5;score++){const choice=node('label'),radio=node('input'),star=node('span',null,'★');radio.type='radio';radio.name=key;radio.value=score;radio.required=true;radio.checked=mine?.[key]===score;radio.setAttribute('aria-label',label+': '+score);choice.append(radio,star);group.append(choice);}form.append(group);}
 const recommend=node('select','fd-input');recommend.setAttribute('aria-label','Рекомендуете преподавателя?');for(const [value,label] of [['yes','Рекомендую'],['no','Не рекомендую']]){const option=node('option',null,label);option.value=value;recommend.append(option);}recommend.value=mine&&!mine.recommend?'no':'yes';
 const comment=node('textarea','fd-input'),author=node('input'),authorLabel=node('label','rating-filter'),counter=node('p','muted'),status=node('p','review-status');comment.maxLength=2000;comment.rows=5;comment.placeholder='Ваш опыт: что понятно, что полезно и что можно улучшить';comment.setAttribute('aria-label','Текст отзыва');comment.value=mine?.comment||'';comment.oninput=()=>counter.textContent=comment.value.length+'/2000';comment.oninput();author.type='checkbox';author.checked=!!mine?.public_author;authorLabel.append(author,node('span',null,'Согласен публиковать моё имя рядом с отзывом для участников факультета'));status.setAttribute('role','status');
 const save=node('button','fd-primary',mine?'Сохранить отзыв':'Отправить отзыв');save.type='submit';form.append(recommend,comment,counter,authorLabel,save,status);host.append(form);
 form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{for(const [key] of ratingCriteria)values[key]=Number(new FormData(form).get(key));await post('teacher-reviews',{teacher:name,...values,recommend:recommend.value==='yes',public_author:author.checked,author_consent:author.checked,comment:comment.value});await go('rating',false);}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};
}

function pushLaunchTarget(){
 const params=new URLSearchParams(location.search),view=params.get('view'),date=params.get('date');
 return {view:['day','deadlines','profile','ratings'].includes(view)?view:'day',date:/^\d{4}-\d{2}-\d{2}$/.test(date||'')&&!Number.isNaN(Date.parse(date))?date:null};
}
async function pushDeviceId(subscription){
 if(!subscription)return '';
 const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(subscription.endpoint));return [...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join('');
}
async function currentPushDevice(){
 if(!('serviceWorker' in navigator))return '';
 try{const registration=await navigator.serviceWorker.getRegistration('/');return await pushDeviceId(await registration?.pushManager?.getSubscription());}catch{return '';}
}
function releaseBrowserPush(){
 if('serviceWorker' in navigator)navigator.serviceWorker.getRegistration('/').then(reg=>reg?.pushManager?.getSubscription()).then(sub=>sub?.unsubscribe()).catch(()=>{});
}
async function webPushSettings(host){
 const section=node('section','web-push-settings'),status=node('p','muted'),intro=node('p','muted','Уведомления на этом устройстве, даже когда дневник закрыт. Настройки Telegram находятся отдельно.');status.setAttribute('role','status');
 section.append(node('h2',null,'Уведомления на телефон'),intro);host.append(section);
 const apple=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1),standalone=matchMedia('(display-mode: standalone)').matches||navigator.standalone;
 if(apple&&!standalone){section.append(node('p','push-install-help','На iPhone: откройте сайт в Safari → «Поделиться» → «На экран Домой». Включите «Открывать как веб-приложение», если этот переключатель есть. Запустите дневник с новой иконки и нажмите «Включить уведомления». Нужна iOS 16.4 или новее.'));return;}
 if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){section.append(node('p','muted','В этом браузере уведомления недоступны. На iPhone используйте приложение, добавленное на экран «Домой» из Safari.'));return;}
 const enable=node('button','fd-primary','Включить уведомления'),disable=button('Отключить на этом устройстве',disconnect),test=button('Проверить уведомление',testPush),controls=node('div','push-device-controls');enable.type='button';enable.disabled=true;controls.append(enable,test,disable);section.append(controls,status);
 let registration,subscription,config,device='',connected=false;
 function draw(){enable.hidden=connected;enable.disabled=!config;disable.hidden=!connected;test.hidden=!connected;}
 function permissionError(){return Notification.permission==='denied'?'Уведомления запрещены. На iPhone откройте «Настройки» → «Уведомления» → «Midiary», разрешите их и вернитесь сюда.':'Разрешение на уведомления не получено.';}
 enable.onclick=()=>{
  // Permission is requested directly in the click handler, before any asynchronous work.
  const permission=Notification.permission==='granted'?Promise.resolve('granted'):Notification.requestPermission();enable.disabled=true;
  (async()=>{try{
   if(await permission!=='granted')throw Error(permissionError());
   registration=await navigator.serviceWorker.register('/sw.js');registration=await navigator.serviceWorker.ready;
   subscription=await registration.pushManager.getSubscription();
   if(!subscription){const key=config.public_key.replace(/-/g,'+').replace(/_/g,'/'),decoded=atob(key+'='.repeat((4-key.length%4)%4));subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:Uint8Array.from(decoded,c=>c.charCodeAt(0))});}
   const response=await post('push/subscribe',{subscription:subscription.toJSON()});device=response.device;connected=true;status.textContent='Уведомления включены. Нажмите «Проверить уведомление» и затем закройте дневник, чтобы проверить получение.';
  }catch(error){status.textContent=error.name==='NotAllowedError'?permissionError():error.message;}finally{draw();}})();
 };
 async function disconnect(){disable.disabled=true;try{await post('push/unsubscribe',{device});connected=false;if(subscription)await subscription.unsubscribe();subscription=null;status.textContent='Уведомления на этом устройстве отключены.';}catch(error){status.textContent=error.message;}finally{disable.disabled=false;draw();}}
 async function testPush(){test.disabled=true;try{await post('push/test',{device});status.textContent='Сервис принял проверочное уведомление. Если оно не появилось, проверьте разрешения и режим «Фокусирование» на телефоне.';}catch(error){status.textContent=error.message;}finally{test.disabled=false;}}
 try{
  registration=await navigator.serviceWorker.getRegistration('/');subscription=await registration?.pushManager?.getSubscription();device=await pushDeviceId(subscription);
  config=await api('push?device='+device);if(!host.isConnected)return;connected=config.subscribed&&Notification.permission==='granted';status.textContent=connected?'Уведомления на этом устройстве включены.':Notification.permission==='denied'?permissionError():'Нажмите кнопку и разрешите уведомления в системном окне.';draw();
  const form=node('form','push-preferences'),fields={};
  for(const [key,label] of [['lessons','Пары из моего расписания'],['deadlines','Все дедлайны группы']]){const row=node('label','rating-filter'),input=node('input');input.type='checkbox';input.checked=!!config.preferences[key];fields[key]=input;row.append(input,node('span',null,label));form.append(row);}
  for(const [key,label,values] of [['lesson_minutes','Когда напоминать о парах',[[0,'В начале пары'],[5,'За 5 минут'],[10,'За 10 минут'],[15,'За 15 минут'],[30,'За 30 минут'],[60,'За час']]],['deadline_minutes','Когда напоминать о дедлайнах',[[0,'В момент дедлайна'],[15,'За 15 минут'],[60,'За час'],[180,'За 3 часа'],[1440,'За сутки'],[2880,'За 2 суток']]]]){
   fields[key]=offsetPicker(form,label,values.map(x=>x[0]),config.preferences[key.replace('_minutes','_offsets')]||[config.preferences[key]]);
  }
  const save=node('button','fd-secondary','Сохранить настройки уведомлений'),saveStatus=node('p','muted');saveStatus.setAttribute('role','status');save.type='submit';form.append(save,node('p','muted','Эти настройки общие для ваших подключённых устройств. Удалённые пары не присылают уведомлений; личные и еженедельные занятия учитываются.'),saveStatus);section.append(form);
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await post('push/preferences',{lessons:fields.lessons.checked,deadlines:fields.deadlines.checked,lesson_offsets:fields.lesson_minutes.values(),deadline_offsets:fields.deadline_minutes.values()});saveStatus.textContent='Настройки сохранены.';}catch(error){saveStatus.textContent=error.message;}finally{save.disabled=false;}};
 }catch(error){status.textContent='Не удалось загрузить настройки: '+error.message;test.hidden=true;disable.hidden=true;}
}
