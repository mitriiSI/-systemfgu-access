/* Admission limits, administrator group assignments and personal profile names. */
const adminGroupsCache=new Map();
function adminDetails(host,title,load){
 const details=node('details','fd-hw-editor admin-panel'),panel=node('div','admin-panel-body');details.append(node('summary',null,title),panel);host.append(details);
 if(title==='Подписки и персональные цены')details.dataset.tour='subscription';
 let loading=false;details.ontoggle=async()=>{if(!details.open||loading||panel.childNodes.length)return;loading=true;try{await load(panel);}catch(error){panel.replaceChildren(node('p','muted',error.message),button('Повторить',()=>{panel.replaceChildren();details.open=false;details.open=true;}));}finally{loading=false;}};return details;
}
async function adminGroupPicker(host,initial='fgu:1457'){
 const wrap=node('div','admin-group-picker'),faculty=selectField(wrap,'Факультет для назначения'),group=selectField(wrap,'Группа для назначения');host.append(wrap);group.required=true;
 for(const [key,info] of Object.entries(facultyInfo))if(info.visible!==false)option(faculty,key,info.short);
 let generation=0;const status=node('p','muted');status.setAttribute('role','status');wrap.append(status);
 async function draw(key){
  const attempt=++generation,value=faculty.value;group.disabled=true;group.replaceChildren();status.textContent='Загружаем группы…';
  try{let rows=adminGroupsCache.get(value);if(!rows){rows=await api('groups?faculty='+value+'&admin=1');adminGroupsCache.set(value,rows);}if(attempt!==generation)return;
   for(const row of rows)option(group,row.id,row.name+' · '+row.level+' · курс '+row.course+(row.program?' · '+row.program:''));
   if(key&&rows.some(row=>row.id===key))group.value=key;else if(value==='fgu'&&rows.some(row=>row.id==='fgu:1457'))group.value='fgu:1457';
   status.textContent=rows.length?'Группу назначает только администратор.':'Группы пока не найдены.';
  }catch(error){if(attempt===generation)status.textContent=error.message;}finally{if(attempt===generation)group.disabled=false;}
 }
 faculty.onchange=()=>draw();faculty.value=facultyInfo[initial.split(':')[0]]?.visible===false?'fgu':initial.split(':')[0];await draw(initial);
 return {value:()=>group.value,set:async key=>{const value=(key||'fgu:1457').split(':')[0];faculty.value=facultyInfo[value]?.visible===false?'fgu':value;await draw(key);}};
}
function guardianFields(form){
 const minor=node('input'),confirmed=node('input');minor.type=confirmed.type='checkbox';const age=node('label','privacy-check'),consent=node('label','privacy-check');
 age.append(minor,node('span',null,'Для участников младше 18 лет'));consent.hidden=true;consent.append(confirmed,node('span',null,'Получил и сохранил отдельное согласие представителя каждого приглашённого несовершеннолетнего'),legalLink('guardian','Согласие представителя'));
 minor.onchange=()=>{consent.hidden=!minor.checked;confirmed.required=minor.checked;confirmed.checked=false;};form.append(age,consent);
 return ()=>({minor:minor.checked,guardian_confirmed:confirmed.checked});
}
function profileNameEditor(host,display){
 if(me.admin)return;const form=node('form','profile-name-form'),name=inputField(form,'Моё имя и фамилия');name.value=me.name;name.required=true;name.minLength=2;name.maxLength=200;name.autocomplete='name';
 const save=node('button','fd-primary','Сохранить имя'),status=node('p','muted');save.type='submit';status.setAttribute('role','status');form.append(save,status);host.append(form);
 form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{const result=await post('account/name',{name:name.value});me.name=result.name;name.value=result.name;display.textContent=result.name;updateHeaderIdentity();const identity=host.querySelector('.identity-row');if(identity){identity.setAttribute('aria-label','Открыть профиль: '+result.name);identity.querySelector('.identity-copy strong').textContent=result.name;identity.querySelector('.identity-avatar').textContent=result.name.split(/\s+/).slice(0,2).map(part=>part[0]).join('');}delete form.dataset.dirty;status.textContent='Имя сохранено.';}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};
}
function privacyInvitations(host){
 adminDetails(host,'Доступ и приглашения',async panel=>{
  panel.append(node('p','muted','Вы задаёте число регистраций по коду или разрешаете регистрацию конкретному Telegram ID. Доступ действует 7 дней. По умолчанию назначается 107пб.'));
  const form=node('form','admin-invite-form');form.append(node('h2',null,'Код приглашения'));const count=inputField(form,'Количество регистраций','number');count.min=1;count.max=10000;count.step=1;count.required=true;count.value=1;panel.append(form);const picker=await adminGroupPicker(form),guardian=guardianFields(form);
  const create=node('button','fd-primary','Создать код приглашения'),result=node('div','admin-invite-result'),status=node('p','muted');create.type='submit';status.setAttribute('role','status');form.append(create,status,result);
  const telegramForm=node('form','admin-telegram-form');telegramForm.append(node('h2',null,'Разрешение по Telegram ID'));const tgId=inputField(telegramForm,'Telegram ID');tgId.inputMode='numeric';tgId.pattern='[0-9]+';tgId.maxLength=19;tgId.required=true;telegramForm.append(node('p','muted','Участник узнаёт свой ID командой /myid. После разрешения он отправляет /register боту дневника; код вводить не нужно.'));panel.append(telegramForm);
  const tgPicker=await adminGroupPicker(telegramForm),tgGuardian=guardianFields(telegramForm),allow=node('button','fd-primary','Разрешить регистрацию'),tgStatus=node('p','muted');allow.type='submit';tgStatus.setAttribute('role','status');telegramForm.append(allow,tgStatus);
  const list=node('section','admin-admissions-list');panel.append(node('h2',null,'Выданные разрешения'),list);
  async function refresh(){
   const data=await api('admin/admissions');list.replaceChildren();
   const statuses={active:'действует',revoked:'отозвано',expired:'срок истёк',used:'использовано'};
   for(const [kind,rows] of [['invite',data.invites],['telegram',data.telegram]])for(const row of rows){
    const item=node('div','admin-access-row'),group=[...adminGroupsCache.values()].flat().find(g=>g.id===row.group_id),label=kind==='invite'?'Приглашение · '+row.used+' из '+row.count+' регистраций':'Telegram ID '+row.id;
    item.append(node('strong',null,label),node('p','muted',(group?.name||row.group_id)+' · '+statuses[row.status]+(row.minor?' · до 18 лет':'')),node('p','muted','До '+new Date(row.expires*1000).toLocaleString(uiLanguage()==='ru'?'ru-RU':uiLanguage())));
    if(row.status==='active')item.append(button('Отозвать разрешение',async()=>{await post('admin/admissions/revoke',{kind,id:row.id});await refresh();}));list.append(item);
   }
   if(!list.childNodes.length)list.append(node('p','muted','Выданных разрешений пока нет.'));
  }
  form.onsubmit=async event=>{event.preventDefault();create.disabled=true;try{
   if(!picker.value())throw Error('Выберите группу');const data=await post('admin/invites',{count:Number(count.value),group_id:picker.value(),...guardian()}),code=node('code','account-code',data.code);code.dataset.noTranslate='';
   result.replaceChildren(code,node('p','muted','Лимит: '+data.count+' · действует 7 дней'),button('Скопировать код',async()=>{await navigator.clipboard.writeText(data.code);status.textContent='Код скопирован.';}));status.textContent='Приглашение создано. Сохраните код: он показывается только сейчас.';await refresh();
  }catch(error){status.textContent=error.message;}finally{create.disabled=false;}};
  telegramForm.onsubmit=async event=>{event.preventDefault();allow.disabled=true;try{if(!tgPicker.value())throw Error('Выберите группу');const data=await post('admin/registrations/telegram',{tg:tgId.value,group_id:tgPicker.value(),...tgGuardian()});tgStatus.textContent='Регистрация разрешена Telegram ID '+data.tg+'. Участнику нужно отправить /register.';await refresh();}catch(error){tgStatus.textContent=error.message;}finally{allow.disabled=false;}};
  await refresh();
 });
 adminDetails(host,'Группы участников',async panel=>{
  panel.append(node('p','muted','Участник меняет своё имя в профиле. Факультет и учебную группу назначаете вы.'));
  const data=await api('admin/members'),form=node('form','admin-member-form'),member=selectField(form,'Участник');member.required=true;panel.append(form);
  if(!data.members.length){panel.append(node('p','muted','Участников пока нет.'));return;}
  for(const row of data.members)option(member,row.id,row.name+(row.tg?' · Telegram '+row.tg:'')+(row.active?'':' · доступ отключён'));
  const info=node('p','muted');form.append(info);const picker=await adminGroupPicker(form,data.members[0].group_id||'fgu:1457');
  function selected(){return data.members.find(row=>row.id===member.value);}
  function describe(){const row=selected();info.textContent='Текущая группа: '+(row?.group_name||'107пб');}
  member.onchange=async()=>{describe();await picker.set(selected()?.group_id);};describe();
  const save=node('button','fd-primary','Назначить группу'),status=node('p','muted');save.type='submit';status.setAttribute('role','status');form.append(save,status);
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;member.disabled=true;try{if(!picker.value())throw Error('Выберите группу');const changed=await post('admin/members',{member:member.value,group_id:picker.value()}),updated=changed.members.find(row=>row.id===member.value);Object.assign(selected(),updated);describe();status.textContent='Группа назначена. Участнику нужно обновить дневник.';}catch(error){status.textContent=error.message;}finally{save.disabled=false;member.disabled=false;}};
 });
 adminDetails(host,'Настройки бота поддержки',async panel=>{
  let info=await api('admin/support');const form=node('form','admin-support-form');panel.append(node('p','muted','Обращения будут приходить вам в @midiarybot. Ответьте на полученное сообщение, чтобы отправить ответ человеку. Сначала отправьте этому боту /start.'),form);
  const token=inputField(form,'Токен @midiarybot','password');token.autocomplete='new-password';token.spellcheck=false;token.required=!info.configured;
  form.append(node('p','muted','Введите токен здесь. После сохранения он не отображается. Пустое поле сохраняет уже подключённого бота.'));
  const recipient=selectField(form,'Получатель обращений');for(const id of info.recipients)option(recipient,id,'Telegram ID '+id);recipient.value=String(info.recipient);
  const save=node('button','fd-primary','Подключить поддержку'),status=node('p','muted'),delivery=node('p','muted');save.type='submit';status.setAttribute('role','status');form.append(save,status,delivery);
  function draw(){delivery.textContent=(info.enabled&&info.configured?'Подключение настроено.':'Бот поддержки отключён.')+' Ожидают доставки: '+info.pending+'. Ошибки доставки: '+info.failed+'.'+(info.last_poll_at?' Последняя проверка: '+new Date(info.last_poll_at*1000).toLocaleString('ru-RU')+'.':'')+(info.last_error?' Ошибка: '+info.last_error+'.':'');token.required=!info.configured;}
  draw();form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{info=await post('admin/support',{token:token.value,recipient:Number(recipient.value),enabled:true});status.textContent='Настройки сохранены. Следите за состоянием доставки ниже.';draw();}catch(error){status.textContent=error.message;}finally{token.value='';save.disabled=false;}};
  panel.append(button('Обновить состояние',async()=>{info=await api('admin/support');draw();}),button('Повторить доставку с ошибкой',async()=>{info=await post('admin/support',{retry:true});draw();}),button('Отключить поддержку',async()=>{info=await post('admin/support',{enabled:false});draw();}));
 });
}
