// Controls shared by official lessons, extra lessons and their detail pages.
iconPaths.gear = '<path d="m9.5 3-.5 2-2 1-2-.5L3 9l1.5 1.5v3L3 15l1.5 3.5 2-.5 2 1 .5 2h6l.5-2 2-1 2 .5L21 15l-1.5-1.5v-3L21 9l-1.5-3.5-2 .5-2-1-.5-2Z"/><circle cx="12" cy="12" r="3"/>';

function teacherNames(record){
 const value=Array.isArray(record)?record:Array.isArray(record?.teachers)?record.teachers:String(record?.teacher||record?.teachersNameFull||record?.teachersName||'').split(/[;,\n|]+/);
 const seen=new Set();return value.filter(name=>typeof name==='string').map(name=>name.trim().replace(/\s+/g,' ')).filter(name=>{const key=name.toLocaleLowerCase('ru').replaceAll('ё','е');if(!name||seen.has(key))return false;seen.add(key);return true;});
}

function teacherLinks(host,record,placeholder=false){
 const names=teacherNames(record),list=node('div','lesson-teachers');
 for(const name of names){const link=button(name,()=>{selectedTeacher=name;go('teacher');},'fd-teacher-link');link.dataset.personName='';list.append(link);}
 if(!names.length&&placeholder)list.append(node('p','muted','Преподаватель не указан'));
 if(list.childNodes.length)host.append(list);
}

function lessonCardHeading(card,lesson,badge=lesson.type){
 const heading=node('div','lesson-card-heading');heading.append(lessonBadge(badge));if(typeof historyPointsBadge==='function')historyPointsBadge(heading,lesson);teacherLinks(heading,lesson);card.append(heading);
}
function lessonFileItems(item){
 const parts=item.split('|');return parts.length===5&&/^teacher:[a-f0-9]{24}$/.test(parts[4])?[item,[...parts.slice(0,4),''].join('|')]:[item];
}
function lessonCardTitle(card,lesson){
 const body=node('div','lesson-card-body'),title=node('div','lesson-card-title');title.append(button(lesson.title,()=>{selectedLesson=lesson;go('lesson');},'fd-lesson-name'));
 body.append(title);card.append(body);
 const items=lessonFileItems(lesson.key),files=(scheduleInfo.files||[]).filter(file=>items.includes(file.item));if(!files.length)return;
 const attachments=node('div','lesson-attachments');attachments.setAttribute('role','group');attachments.setAttribute('aria-label','Файлы по предмету '+lesson.title);
 for(const file of files)attachments.append(fileDownloadRow(file,true));card.append(attachments);
}
async function openLessonHomework(lesson){
 selectedLesson=lesson;await go('lesson');const editor=screen.querySelector('[data-homework-editor]');if(!editor)return;editor.open=true;editor.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});editor.querySelector('textarea')?.focus({preventScroll:true});
}
async function openLessonUpload(lesson){
 selectedLesson=lesson;await go('lesson');const form=screen.querySelector('.upload-form');if(!form)return;form.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});form.querySelector('input[type=file]')?.focus({preventScroll:true});
}

function teacherFields(form,initial=[]){
 const fieldset=node('fieldset','lesson-teacher-fields'),rows=node('div','lesson-teacher-rows');fieldset.append(node('legend',null,'Преподаватели'),rows);form.append(fieldset);
 const add=button('Добавить преподавателя',()=>append(''),'fd-secondary teacher-add');fieldset.append(add);
 function update(){const entries=[...rows.children];entries.forEach((row,index)=>{row.querySelector('label').firstChild.textContent='Преподаватель '+(index+1);row.querySelector('input').setAttribute('aria-label','Преподаватель '+(index+1));row.querySelector('button').setAttribute('aria-label','Убрать преподавателя '+(index+1));});add.disabled=entries.length>=10;}
 function append(value){if(rows.children.length>=10)return;const row=node('div','lesson-teacher-row'),label=node('label','fd-label','Преподаватель'),input=node('input','fd-input');input.type='text';input.value=value;input.maxLength=200;input.autocomplete='name';input.dataset.noTranslate='';label.append(input);const remove=button('×',()=>{if(rows.children.length===1)input.value='';else row.remove();update();form.dataset.dirty='true';},'fd-icon-button teacher-remove');row.append(label,remove);rows.append(row);update();if(value===''&&rows.children.length>1){input.focus();form.dataset.dirty='true';}}
 function reset(values=[]){rows.replaceChildren();for(const name of values.length?values:[''])append(name);update();}
 reset(initial);return {element:fieldset,values:()=>teacherNames([...rows.querySelectorAll('input')].map(input=>input.value)),reset};
}

function editSubjectTeachers(lesson){
 const dialog=node('dialog','subject-teachers-dialog'),form=node('form'),heading=node('h2',null,'Преподаватели предмета');heading.id='subject-teachers-heading';dialog.setAttribute('aria-labelledby',heading.id);
 const close=button('Закрыть',()=>dialog.close(),'fd-secondary');form.append(heading,node('p','subject-teachers-title',lesson.title),node('p','muted','Список общий для группы и применяется ко всем занятиям этого предмета.'));
 const teachers=teacherFields(form,teacherNames(lesson)),status=node('p','muted');status.setAttribute('role','status');
 const save=node('button','fd-primary',me.moderate&&!me.admin?'Отправить администратору':'Сохранить преподавателей');save.type='submit';
 async function submit(body){save.disabled=true;restore.disabled=true;try{const result=await post('schedule/teachers',{title:lesson.rawTitle||lesson.title,...body});if(result.status==='pending'){status.textContent='Отправлено администратору на подтверждение';delete form.dataset.dirty;return;}dialog.close();await load(true);await go('day',false);}catch(error){status.textContent=error.message;}finally{save.disabled=false;restore.disabled=false;}}
 const restore=button('Вернуть преподавателей из расписания',()=>submit({restore:true}),'fd-secondary');form.append(save,restore,close,status);
 form.onsubmit=event=>{event.preventDefault();submit({teachers:teachers.values()});};dialog.append(form);root.append(dialog);
 dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close();}});
 dialog.showModal();teachers.element.querySelector('input').focus();
}

function editLessonTime(lesson){
 const dialog=node('dialog','subject-teachers-dialog'),form=node('form'),heading=node('h2',null,'Время пары');
 dialog.setAttribute('aria-label','Время пары');form.append(heading,node('p',null,lesson.title),node('p','muted','Изменение только для вас на '+dateLabel(lesson.date)+'. Напоминания придут по новому времени.'));
 const start=inputField(form,'Начало пары (МСК)','time'),end=inputField(form,'Окончание пары (МСК)','time');start.value=lesson.start||'';end.value=lesson.end||'';start.required=end.required=true;
 const save=node('button','fd-primary','Сохранить время');save.type='submit';const status=node('p','muted');status.setAttribute('role','status');
 async function submit(values){save.disabled=true;try{await post('schedule/time',{id:lesson.occurrence_id||lesson.schedule_id,date:lesson.date,...values});dialog.close();await load(true);await go('day',false);}catch(error){status.textContent=error.message;}finally{save.disabled=false;}}
 form.onsubmit=event=>{event.preventDefault();submit({start:start.value,end:end.value});};form.append(save);
 if(lesson._time_override)form.append(button('Вернуть время из расписания',()=>submit({restore:true})));
 form.append(button('Закрыть',()=>dialog.close()),status);dialog.append(form);root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();start.focus();
}

let openLessonSettings=null,lessonSettingsId=0;
function editLessonRoom(lesson){
 const dialog=node('dialog','subject-teachers-dialog'),form=node('form');dialog.setAttribute('aria-label','Аудитория пары');
 form.append(node('h2',null,'Аудитория пары'),node('p',null,lesson.title),node('p','muted','Изменение только для вас на '+dateLabel(lesson.date)+'.'));
 const room=inputField(form,'Аудитория или адрес','text');room.value=lesson.room||'';room.maxLength=120;
 const save=node('button','fd-primary','Сохранить аудиторию'),status=node('p','muted');save.type='submit';status.setAttribute('role','status');
 async function submit(values){save.disabled=true;try{await post('schedule/room',{id:lesson.occurrence_id||lesson.schedule_id,date:lesson.date,...values});dialog.close();await load(true);await go('day',false);}catch(error){status.textContent=error.message;}finally{save.disabled=false;}}
 form.onsubmit=event=>{event.preventDefault();submit({room:room.value.trim()});};form.append(save);
 if(lesson._room_override)form.append(button('Вернуть аудиторию из расписания',()=>submit({restore:true})));
 form.append(button('Закрыть',()=>dialog.close()),status);dialog.append(form);root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();room.focus();
}
function closeLessonSettings(focus=false){if(!openLessonSettings)return;const {toggle,panel,host}=openLessonSettings;panel.hidden=true;toggle.setAttribute('aria-expanded','false');host.classList.remove('is-settings-open');openLessonSettings=null;if(focus&&toggle.isConnected)toggle.focus();}
function positionLessonSettings(toggle,panel){
 panel.classList.remove('opens-up');panel.style.maxHeight='';const box=toggle.getBoundingClientRect(),nav=document.getElementById('nav'),header=document.querySelector('.fd-telegram');
 const bottom=Math.min(window.innerHeight-12,nav&&!nav.hidden?nav.getBoundingClientRect().top-10:window.innerHeight-12),top=Math.max(12,header?header.getBoundingClientRect().bottom+10:12),below=bottom-box.bottom-8,above=box.top-top-8;
 const up=panel.scrollHeight>below&&above>below;panel.classList.toggle('opens-up',up);panel.style.maxHeight=Math.max(44,up?above:below)+'px';
}
document.addEventListener('pointerdown',event=>{if(openLessonSettings&&!openLessonSettings.toggle.parentElement.contains(event.target))closeLessonSettings();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&openLessonSettings){event.preventDefault();closeLessonSettings(true);}});

function lessonSettings(host,lesson){
 const settings=node('div','lesson-settings'),panel=node('div','lesson-settings-panel');panel.id='lesson-settings-'+(++lessonSettingsId);panel.hidden=true;panel.setAttribute('role','group');panel.setAttribute('aria-label','Действия с занятием');
 const toggle=iconButton('gear','Настройки занятия',()=>{});toggle.classList.add('lesson-settings-toggle');toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-controls',panel.id);
 toggle.addEventListener('animationend',event=>{if(event.target===toggle)toggle.classList.remove('is-gear-animating');});
 toggle.onclick=event=>{event.stopPropagation();toggle.classList.remove('is-gear-animating');if(!matchMedia('(prefers-reduced-motion: reduce)').matches){void toggle.offsetWidth;toggle.classList.add('is-gear-animating');}const opened=!panel.hidden;closeLessonSettings();if(!opened){panel.hidden=false;toggle.setAttribute('aria-expanded','true');host.classList.add('is-settings-open');openLessonSettings={toggle,panel,host};positionLessonSettings(toggle,panel);}};
 function action(title,run,destructive=false){panel.append(button(title,async()=>{closeLessonSettings();await run();},'lesson-settings-action'+(destructive?' is-destructive':'')));}
 if(lesson.type!=='event')action(content('homework',lesson.key)?'Изменить ДЗ':'Добавить ДЗ',()=>openLessonHomework(lesson));
 action('Добавить файл',()=>openLessonUpload(lesson));
 if(typeof isHistorySubject==='function'&&isHistorySubject(lesson.title))action(hpText('add')+' · '+hpText('heading'),()=>openHistoryPoints(lesson,true));
 if(['fgu','fgp'].includes(me.faculty)&&lesson.type!=='event'&&(lesson.occurrence_id||lesson.schedule_id)){
  action('Изменить время пары',()=>editLessonTime(lesson));action('Изменить аудиторию',()=>editLessonRoom(lesson));
 }
 if(lesson.type!=='event')action('Изменить преподавателей',()=>editSubjectTeachers(lesson));
 if(lesson.occurrence_id||lesson.schedule_id)action(lesson.type==='event'?'Убрать у меня на эту дату':'Убрать пару у меня на эту дату',()=>hideLesson(lesson),true);
 if(lesson.source==='custom'&&lesson.can_delete)action(lesson.recurrence==='weekly'?'Отключить повторение':'Удалить добавленную запись',async()=>{await post('schedule/custom',{id:lesson.id,disable:true});await load(true);await go('day',false);},true);
 if(lesson.source==='shared'&&lesson.can_delete)action('Убрать из расписания всей группы',async()=>{if(!confirm('Убрать «'+lesson.title+'» из расписания всей группы?'))return;const result=await post('schedule/events',{id:lesson.id,delete:true});if(result.status==='pending'){document.getElementById('status').textContent='Удаление отправлено администратору на подтверждение';return;}await load(true);await go('day',false);},true);
 if(!panel.childNodes.length)return;host.classList.add('has-lesson-settings');settings.append(toggle,panel);host.append(settings);
}

function daySwipes(host,week){
 host.classList.add('day-swipes');let gesture=null,suppressClick=false;
 host.addEventListener('pointerdown',event=>{suppressClick=false;gesture=null;if(!event.isPrimary||!['touch','pen'].includes(event.pointerType))return;const target=event.target;if(week.contains(target)||target.closest('input,textarea,select,a,summary,.lesson-settings,button'))return;gesture={id:event.pointerId,x:event.clientX,y:event.clientY};});
 host.addEventListener('pointercancel',()=>gesture=null);
 host.addEventListener('pointerup',event=>{if(!gesture||gesture.id!==event.pointerId)return;const start=gesture;gesture=null;const dx=event.clientX-start.x,dy=event.clientY-start.y;if(Math.abs(dx)<60||Math.abs(dx)<Math.abs(dy)*1.5)return;suppressClick=true;event.preventDefault();changeDay(addDays(selectedDay,dx<0?1:-1)).catch(fail);});
 host.addEventListener('click',event=>{if(!suppressClick)return;suppressClick=false;event.preventDefault();event.stopPropagation();},true);
}
