function languagePicker(){
 const row=document.createElement('label');row.className='language-picker';row.append(document.createTextNode('Язык / Language / 语言'));
 const select=document.createElement('select');select.className='fd-input';select.setAttribute('aria-label','Language');
 for(const [value,text] of [['ru','Русский'],['en','English'],['zh','中文']]){const o=document.createElement('option');o.value=value;o.textContent=text;o.dataset.noTranslate='';o.lang=value;select.append(o);}select.value=uiLanguage();
 select.onchange=async()=>{setUiLanguage(select.value);if(me)try{await post('language',{language:select.value});}catch(e){fail(e);}translateInterface();if(me&&!fileView&&root.dataset.page!=='consent')await go(page,false);};row.append(select);return row;
}
function readerStatus(text){document.getElementById('status').textContent=text;}
function offsetPicker(host,label,choices,selected){
 const set=node('fieldset','reminder-offsets');set.append(node('legend',null,label));const inputs=[];
 for(const value of choices){const row=node('label','offset-chip'),input=node('input');input.type='checkbox';input.value=value;input.checked=selected.includes(value);inputs.push(input);row.append(input,node('span',null,value===0?'В момент события':value===1440?'За сутки':value===2880?'За 2 суток':'За '+value+' мин.'));set.append(row);}host.append(set);return {values:()=>inputs.filter(x=>x.checked).map(x=>Number(x.value))};
}
async function accountAccess(host){
 const section=node('section','account-access');section.dataset.tour='account-code';section.append(node('h3',null,'Мой код доступа'));const panel=node('div');section.append(panel);host.append(section);
 try{const data=await api('account-code');if(!section.isConnected)return;const code=node('code','account-code',data.code||'Код администратора задаётся командой /mycode');code.dataset.noTranslate='';panel.append(code,node('p','muted','Сохраните код для входа. Для уведомлений отправьте боту /link и этот код.'));
  if(data.code)panel.append(button('Скопировать код',async()=>{await navigator.clipboard.writeText(data.code);readerStatus('Код скопирован.');}));
 }catch(e){panel.append(node('p','muted',e.message));}
}
let daySelectionVersion=0;
async function changeDay(value,options={}){
 if(value===selectedDay&&page==='day')return;
 const version=++daySelectionVersion,direction=value>selectedDay?1:-1;selectedDay=value;
 const host=screen.querySelector('.day-page');
 if(page!=='day'||!host?.dayNavigation){await go('day',false);return;}
 closeLessonSettings();host.dayNavigation.select(value,options);host.dayNavigation.details.setAttribute('aria-busy','true');
 await load();if(version!==daySelectionVersion||page!=='day'||!host.isConnected)return;
 refreshDayView({animate:true,direction});
}
async function materials(host){
 host.append(node('h1',null,'Учебные материалы'));const data=await api('study-materials');let filter='all';
 const tabs=node('div','material-tabs'),list=node('div','unified-materials');tabs.dataset.tour='material-filters';list.dataset.tour='material-files';host.append(tabs,list);
 function draw(){tabs.replaceChildren();for(const [key,label] of [['all','Все файлы'],['notes','Конспекты'],['literature','Литература'],['personal','Личные записи']]){const tab=button(label,()=>{filter=key;draw();},filter===key?'fd-primary':'fd-secondary');tab.dataset.materialFilter=key;tab.setAttribute('aria-pressed',String(filter===key));tabs.append(tab);}list.replaceChildren();
  if(filter!=='personal'){const files=data.files.filter(f=>filter==='all'||f.category===filter);if(!files.length)list.append(node('p','muted','Файлов пока нет'));
   for(const subject of [...new Set(files.map(f=>f.subject))]){list.append(node('h2',null,subject?subjectDisplay(subject):'Без предмета'));for(const file of files.filter(f=>f.subject===subject)){list.append(fileDownloadRow(file));}}
  }else{notes(list);}
 }
 draw();
 const collections=node('details','fd-hw-editor');collections.dataset.tour='collections';collections.append(node('summary',null,'Подборки и загрузка материалов'));const collectionHost=node('section');collections.append(collectionHost);host.append(collections);await collectionMaterials(collectionHost);
 const literature=node('details','fd-hw-editor');literature.dataset.tour='literature';literature.append(node('summary',null,'Темы литературы и загрузка книг'));const literatureHost=node('section');literature.append(literatureHost);host.append(literature);await library(literatureHost);
}

function userText(tag,cls,text){const element=node(tag,cls,text);return element;}

async function homeworkReminderSettings(host){
 const section=node('section','homework-reminders');section.append(node('h2',null,'ДЗ на завтра'),node('p','muted','Напоминание приходит, только если для ваших завтрашних пар записано общее ДЗ. Время московское; настройки общие для Telegram, MAX и включённых уведомлений сайта.'));host.append(section);
 const status=node('p','muted');status.setAttribute('role','status');
 try{const prefs=await api('homework-reminders');if(!host.isConnected)return;
  const chosen=new Set(prefs.times),fields=node('fieldset','reminder-offsets homework-times');fields.append(node('legend',null,'Выбранные времена (МСК)'));const form=node('form');section.append(form);
  function draw(){fields.querySelectorAll('.homework-time,.homework-empty').forEach(row=>row.remove());for(const value of [...chosen].sort((a,b)=>a-b)){const clock=String(Math.floor(value/60)).padStart(2,'0')+':'+String(value%60).padStart(2,'0'),row=node('div','homework-time');const remove=button('×',()=>{chosen.delete(value);form.dataset.dirty='true';draw();},'fd-icon-button homework-time-remove');remove.setAttribute('aria-label','Убрать время '+clock);row.append(node('time',null,clock),remove);fields.append(row);}if(!chosen.size)fields.append(node('p','muted homework-empty','Пока время не выбрано.'));}
  const addRow=node('div','homework-time-add'),time=inputField(addRow,'Добавить время напоминания (МСК)','time');time.step=60;
  function addTime(){if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(time.value)){status.textContent='Выберите время';return;}const [h,m]=time.value.split(':').map(Number),value=h*60+m;if(chosen.has(value)){status.textContent='Это время уже добавлено.';return;}if(chosen.size>=4){status.textContent='Можно выбрать до 4 времён.';return;}chosen.add(value);form.dataset.dirty='true';draw();time.value='';status.textContent='';}
  addRow.append(button('Добавить время',addTime));form.append(node('p','muted','Сначала добавьте удобное время. Можно сохранить до 4 напоминаний в день.'),addRow,fields);draw();
  const save=node('button','fd-primary','Сохранить напоминания о ДЗ');save.type='submit';form.append(save,button('Выключить напоминания о ДЗ',async()=>{await post('homework-reminders',{times:[]});chosen.clear();draw();status.textContent='Напоминания о ДЗ выключены.';}),status);
  form.onsubmit=async event=>{event.preventDefault();if(time.value){addTime();if(time.value)return;}save.disabled=true;try{await post('homework-reminders',{times:[...chosen]});delete form.dataset.dirty;status.textContent=chosen.size?'Напоминания о ДЗ сохранены.':'Напоминания о ДЗ выключены.';}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};
 }catch(error){status.textContent=error.message;section.append(status);}
}

async function notificationChannelSettings(host){
 const section=node('section','notification-channels');section.append(node('h2',null,'Куда присылать уведомления'),node('p','muted','Выбор действует для пар, дедлайнов и ДЗ на завтра. Общие объявления настраиваются отдельно.'));host.append(section);
 const status=node('p','muted');status.setAttribute('role','status');
 try{const prefs=await api('notification-channels');if(!host.isConnected)return;const form=node('form'),fields={};
  for(const [key,title] of [['telegram','Telegram'],['max','MAX'],['website','Уведомления сайта']]){const row=node('label','privacy-check'),input=node('input');input.type='checkbox';input.checked=prefs.channels[key];fields[key]=input;row.append(input,node('span',null,title+(prefs.connected[key]?'':' · ещё не подключено')));form.append(row);}
  const save=node('button','fd-primary','Сохранить каналы уведомлений');save.type='submit';form.append(save,status);section.append(form);
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await post('notification-channels',{channels:Object.fromEntries(Object.entries(fields).map(([key,input])=>[key,input.checked]))});delete form.dataset.dirty;status.textContent='Каналы уведомлений сохранены.';}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};
 }catch(error){status.textContent=error.message;section.append(status);}
}
