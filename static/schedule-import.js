/* Local file recognition, editable preview and explicit personal/group import. */
function importChoicesHint(host){
 const choices=scheduleInfo.import_choices;if(!choices?.available)return;
 const hint=node('section','schedule-status');hint.append(node('p',null,choices.unresolved.length?'Выберите свои языковые подгруппы и предметы по выбору. До выбора варианты скрыты из расписания и напоминаний.':'В расписании показаны выбранные вами предметы и подгруппы.'),button('Выбрать предметы и подгруппы',editImportChoices));host.append(hint);
}
async function editImportChoices(){
 const data=await api('schedule/import/choices'),dialog=node('dialog','subject-teachers-dialog'),form=node('form'),fields={choices:new Map(),subgroups:new Map()};dialog.setAttribute('aria-label','Предметы и подгруппы');form.append(node('h2',null,'Предметы и подгруппы'),node('p','muted','Выбор применяется только к вашему загруженному расписанию. Варианты можно изменить позже.'));
 for(const section of ['choices','subgroups'])for(const row of data[section]){const field=selectField(form,row.label);option(field,'','Выберите свой вариант');option(field,'__none','Не изучаю / не добавлять');row.options.forEach(value=>option(field,value,value));field.value=data.selection[section][row.id]||'';fields[section].set(row.id,field);}
 function branches(){for(const row of data.subgroups){const active=data.choices.every(choice=>!choice.options.includes(row.id)||fields.choices.get(choice.id).value===row.id);fields.subgroups.get(row.id).closest('label').hidden=!active;}}
 for(const field of fields.choices.values())field.onchange=branches;branches();
 const save=node('button','fd-primary','Применить выбранные варианты');save.type='submit';const status=node('p','muted');status.setAttribute('role','status');
 form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await post('schedule/import/choices',Object.fromEntries(Object.entries(fields).map(([section,map])=>[section,Object.fromEntries([...map].map(([id,field])=>[id,field.value]))])));dialog.close();await load(true);await go(page,false);}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};
 form.append(save,button('Закрыть',()=>dialog.close()),status);dialog.append(form);root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
}
async function importSchedulePage(host){
 const personalFaculty=['ffl','fgp'].includes(me.faculty);
 host.append(node('h1',null,'Загрузить расписание'),node('p','muted',me.faculty==='fgp'?'Загрузите PDF расписания ФГП. Выберите свою группу в таблице, проверьте занятия и сохраните их в дневник.':'Загрузите фото таблицы или файл расписания. Выберите свою группу, проверьте распознанные занятия и сохраните их в дневник.'));
 const form=node('form','import-form'),file=inputField(form,'Фото или файл расписания','file');file.accept='.pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.xlsx,.xls';file.required=true;
 form.append(node('p','muted','Фото, PDF и Word — до 15 МБ; Excel — до 5 МБ. На фото должны быть видны дни недели, время и заголовки групп.'));
 const settings=node('details','fd-hw-editor');settings.append(node('summary',null,'Группа в файле и период'));
 const controls=node('div'),tableGroup=selectField(controls,'Группа в таблице');option(tableGroup,'','Определить по моей группе: '+me.group);tableGroup.closest('label').hidden=true;
 const from=inputField(controls,'Начало периода','date'),to=inputField(controls,'Конец периода','date'),anchor=inputField(controls,'Понедельник первой нечётной недели','date');
 controls.append(node('p','muted','Для PDF даты определяются из документа. Для фотографии без дат укажите свой семестр. Чётные и нечётные недели отсчитываются от выбранного понедельника.'));
 const excel=node('div'),sheet=selectField(excel,'Лист Excel'),header=inputField(excel,'Строка заголовков','number');header.min=1;header.max=50;header.value=1;
 const mappingHost=node('div','import-mappings');excel.append(mappingHost);excel.hidden=true;controls.append(excel);settings.append(controls);form.append(settings);
 const preview=node('button','fd-primary','Распознать и проверить');preview.type='submit';const status=node('p','muted');status.setAttribute('role','status');status.setAttribute('aria-live','polite');form.append(preview,status);host.append(form);
 const resultHost=node('section','schedule-import-result');host.append(resultHost);
 let parsed,mappingControls={},mappingReady=false;
 function invalidate(){parsed=null;resultHost.replaceChildren();}
 form.addEventListener('change',invalidate);
 file.onchange=()=>{sheet.replaceChildren();mappingHost.replaceChildren();mappingControls={};mappingReady=false;header.value=1;from.value='';to.value='';anchor.value='';tableGroup.replaceChildren();option(tableGroup,'','Определить по моей группе: '+me.group);tableGroup.closest('label').hidden=true;excel.hidden=!/\.xlsx?$/i.test(file.files[0]?.name||'');if(!excel.hidden){from.value=today();to.value=addDays(today(),90);} };
 sheet.onchange=()=>{mappingReady=false;mappingControls={};mappingHost.replaceChildren();};header.onchange=sheet.onchange;
 form.onsubmit=async event=>{
  event.preventDefault();preview.disabled=true;status.textContent='Читаем таблицу и распознаём занятия… Для фотографии это может занять около минуты.';resultHost.replaceChildren();parsed=null;
  try{
   const body=new FormData(),options={};if(from.value)options.from=from.value;if(to.value)options.to=to.value;if(anchor.value)options.week_anchor=anchor.value;if(tableGroup.value)options.table_group=tableGroup.value;
   if(sheet.value)options.sheet=sheet.value;if(sheet.value||Number(header.value)!==1)options.header_row=Number(header.value);
   if(mappingReady)options.mapping=Object.fromEntries(Object.entries(mappingControls).map(([key,input])=>[key,input.value===''?null:Number(input.value)]));
   body.append('file',file.files[0]);body.append('options',JSON.stringify(options));const data=await api('schedule/import/preview',{method:'POST',body});if(!host.isConnected)return;parsed=data;
   if(data.period){from.value=data.period.from;to.value=data.period.to;anchor.value=data.period.week_anchor;}
   if(data.table_groups?.length){tableGroup.replaceChildren();option(tableGroup,'','Моя группа: '+me.group);data.table_groups.forEach(name=>option(tableGroup,name,name));if(data.table_groups.includes(data.selected_group))tableGroup.value=data.selected_group;tableGroup.closest('label').hidden=false;}
   excel.hidden=data.format!=='excel';
   if(data.format==='excel'){
    sheet.replaceChildren();data.sheets.forEach(name=>option(sheet,name,name));sheet.value=data.sheet;header.value=data.header_row;mappingHost.replaceChildren();mappingControls={};
    const labels={date:'Дата',weekday:'День недели',number:'Номер пары',title:'Предмет',start:'Начало / интервал',end:'Окончание',teacher:'Преподаватель',room:'Аудитория',type:'Тип занятия'};
    for(const [key,label] of Object.entries(labels)){const control=selectField(mappingHost,label);option(control,'','Не используется');data.columns.forEach(column=>option(control,column.index,column.label));control.value=data.mapping[key]??'';mappingControls[key]=control;}mappingReady=true;
   }
   status.textContent=data.error_count?'Проверьте группу и настройки распознавания.':'Распознано '+data.rows.length+' занятий. Проверьте варианты ниже перед сохранением.';
   if(data.error_count){settings.open=true;const list=node('ul','import-errors');data.errors.forEach(error=>list.append(node('li',null,'Страница / строка '+error.row+': '+error.message)));resultHost.append(list);}
   for(const warning of data.warnings||[])resultHost.append(node('p','schedule-status',warning));
   if(data.templates?.length)drawReview(data);
  }catch(error){status.textContent=error.message;}finally{preview.disabled=false;}
 };
 function drawReview(data){
  resultHost.append(node('h2',null,'Проверка занятий'),node('p','muted','Исправьте текст или время в карточке. Снимите галочку с ненужного занятия. Исправления применятся ко всем его повторениям в выбранном периоде.'));
  const filters=node('div','import-subgroups'),branchSelectors=new Map(),choiceSelectors=new Map();resultHost.append(filters);
  const choices=[...new Set(data.templates.map(row=>row.choice).filter(Boolean))];
  for(const key of choices){const rows=data.templates.filter(row=>row.choice===key),titles=[...new Set(rows.map(row=>row.title))];if(titles.length<2)continue;
   const row=rows[0],label=key==='primary-language'?'Какой язык вы изучаете':weekdays[row.weekday]+', '+row.number+' пара — предмет по выбору',control=selectField(filters,label);
   option(control,'','Выберите свой вариант');option(control,'__none','Не добавлять');titles.forEach(title=>option(control,title,title));choiceSelectors.set(key,control);
  }
  const titles=[...new Set(data.templates.filter(row=>row.group).map(row=>row.title))];
  for(const title of titles){const groups=[...new Set(data.templates.filter(row=>row.title===title&&row.group).map(row=>row.group))];if(groups.length<2)continue;const control=selectField(filters,title+' — моя подгруппа');option(control,'','Выберите свою подгруппу');option(control,'__none','Не изучаю этот предмет');option(control,'__all','Все подгруппы (общее расписание)');groups.forEach(group=>option(control,group,group));branchSelectors.set(title,control);}
  const cards=new Map(),dayBlocks=node('div','import-review-days');resultHost.append(dayBlocks);
  for(let day=0;day<7;day++){
   const rows=data.templates.filter(row=>row.weekday===day);if(!rows.length)continue;const block=node('details','import-review-day fd-hw-editor');block.open=day===Math.min(...data.templates.map(row=>row.weekday));block.append(node('summary',null,['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье'][day]+' · '+rows.length+' вариантов'));dayBlocks.append(block);
   for(const row of rows){
    const card=node('div','import-lesson-review'),label=node('label','privacy-check'),enabled=node('input');enabled.type='checkbox';enabled.checked=true;label.append(enabled,node('strong',null,(row.number?row.number+' пара · ':'')+row.start+'–'+row.end+(row.week?' · '+(row.week==='odd'?'нечётная неделя':'чётная неделя'):'')));card.append(label);const fields={};
    fields.title=inputField(card,'Предмет');fields.title.value=row.title;fields.title.maxLength=300;
    const times=node('div','import-time-fields');fields.start=inputField(times,'Начало','time');fields.end=inputField(times,'Окончание','time');fields.start.value=row.start;fields.end.value=row.end;card.append(times);
    const extras=node('details','import-lesson-details');extras.append(node('summary',null,[row.teacher,row.room?'Ауд. '+row.room:'',row.group].filter(Boolean).join(' · ')||'Преподаватель, аудитория и подгруппа'));
    for(const [key,name,limit] of [['teacher','Преподаватель',200],['room','Аудитория',120],['group','Подгруппа',80],['type','Вид занятия',80]]){fields[key]=inputField(extras,name);fields[key].value=row[key]||'';fields[key].maxLength=limit;}
    card.append(extras);block.append(card);cards.set(row.template_id,{card,enabled,fields,row});
   }
  }
  const visibility=selectField(resultHost,'Кому добавить расписание');option(visibility,'personal','Только мне');if(me.admin)option(visibility,'group','Всей моей группе');visibility.value=me.admin&&!personalFaculty?'group':'personal';visibility.closest('label').hidden=!me.admin;
  const replaceLabel=node('label','privacy-check'),replace=node('input');replace.type='checkbox';replaceLabel.append(replace,node('span',null,'Заменить ранее загруженное расписание на даты из файла'));resultHost.append(replaceLabel);
  const count=node('p','muted'),save=button('Сохранить расписание',async()=>{
   save.disabled=true;
   try{
    if(parsed!==data)throw Error('Повторите проверку изменённого файла');const edits={};
    for(const [id,entry] of cards)edits[id]={enabled:included(entry),...Object.fromEntries(Object.entries(entry.fields).map(([key,field])=>[key,field.value]))};
    const result=await post('schedule/import/commit',{token:data.token,replace:replace.checked,visibility:visibility.value,edits});
    const first=data.rows.find(row=>edits[row.template_id]?.enabled);if(first&&data.rows.every(row=>row.date<today()||row.date>today()))selectedDay=first.date;else selectedDay=today();
    await load(true);await go('day',false);document.getElementById('status').textContent='Сохранено '+result.added+' занятий'+(result.visibility==='personal'?' в ваш дневник.':' для группы '+me.group+'.');
   }catch(error){status.textContent=error.message;}finally{save.disabled=false;}
  },'fd-primary');
  function included(entry){const choice=choiceSelectors.get(entry.row.choice),branch=branchSelectors.get(entry.row.title);return entry.enabled.checked&&(!choice||choice.value===entry.row.title)&&(!branch||branch.value===entry.row.group||(branch.value==='__all'&&visibility.value==='group'));}
  function updateCount(){const total=data.rows.filter(row=>{const entry=cards.get(row.template_id);return entry&&included(entry);}).length;let unresolved=false;
   for(const selector of choiceSelectors.values())if(!selector.value)unresolved=true;
   for(const [title,selector] of branchSelectors){const rows=data.templates.filter(row=>row.title===title),active=rows.some(row=>!choiceSelectors.has(row.choice)||choiceSelectors.get(row.choice).value===title);selector.closest('label').hidden=!active;
    if(active&&(!selector.value||(selector.value==='__all'&&visibility.value==='personal')))unresolved=true;
   }
   count.textContent=unresolved?'Выберите предметы по выбору и свои языковые подгруппы.':'Будет сохранено '+total+' занятий'+(visibility.value==='personal'?' только для вас.':' для всей группы.');save.disabled=!data.token||!total||unresolved;
   for(const entry of cards.values()){const choice=choiceSelectors.get(entry.row.choice)?.value,branch=branchSelectors.get(entry.row.title)?.value;entry.card.hidden=Boolean((choice&&choice!==entry.row.title)||(branch&&branch!=='__all'&&entry.row.group&&entry.row.group!==branch));}
  }
  for(const selector of [...choiceSelectors.values(),...branchSelectors.values()])selector.onchange=updateCount;for(const entry of cards.values())entry.enabled.onchange=updateCount;visibility.onchange=updateCount;
  resultHost.append(count,save);updateCount();
 }
}
