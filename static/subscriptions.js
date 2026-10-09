function priceText(value){return value===null?'Цена пока не установлена':new Intl.NumberFormat(uiLocale(),{style:'currency',currency:'RUB'}).format(value/100)+' / месяц';}
function priceInputValue(value){return value===null?'':(value/100).toFixed(2);}
function minorUnits(input){return input.value.trim()===''?null:Math.round(Number(input.value)*100);}
async function subscriptionPanel(host){
 if(!me.admin){
  if(me.faculty==='fgu'){host.append(node('p','muted','ФГУ — бесплатный доступ. Оплата не требуется.'));return;}
  const section=node('section','subscription-personal');section.append(node('h2',null,'Подписка'));host.append(section);try{const value=await api('subscription');section.append(node('p',null,value.mode==='personal_free'?'Вам назначен бесплатный доступ.':priceText(value.price)),node('p','muted','Подписка готовится. Сейчас все функции доступны, платежи не принимаются.'));if(value.mode==='personal_free'&&value.free_until)section.append(node('p','muted','Бесплатно до '+new Date(value.free_until*1000).toLocaleDateString(uiLocale())));}catch(error){section.append(node('p',null,error.message));}return;
 }
 adminDetails(host,'Подписки и персональные цены',async panel=>{
  let info=await api('admin/subscriptions');panel.append(node('p','muted','ФГУ всегда бесплатно. Для остальных факультетов можно подготовить месячную цену и персональные условия. Приём платежей пока отключён; доступ к функциям открыт.'));
  const baseForm=node('form','subscription-base-form'),base=inputField(baseForm,'Базовая цена в рублях','number');base.min=0;base.max=1000000;base.step='.01';base.value=priceInputValue(info.base_price);const saveBase=node('button','fd-primary','Сохранить базовую цену'),baseStatus=node('p','muted');saveBase.type='submit';baseStatus.setAttribute('role','status');baseForm.append(saveBase,baseStatus);panel.append(baseForm);
  baseForm.onsubmit=async event=>{event.preventDefault();saveBase.disabled=true;try{info=await post('admin/subscriptions',{base_price:minorUnits(base)});baseStatus.textContent='Базовая цена сохранена. Приём платежей отключён.';}catch(error){baseStatus.textContent=error.message;}finally{saveBase.disabled=false;}};
  if(!info.members.length){panel.append(node('p','muted','Участников других факультетов пока нет.'));return;}
  const form=node('form','subscription-member-form'),member=selectField(form,'Участник для персональной цены');for(const row of info.members)option(member,row.id,row.name+(row.tg?' · Telegram '+row.tg:''));
  const current=node('p','muted'),cost=inputField(form,'Персональная цена в рублях','number');cost.min=0;cost.max=1000000;cost.step='.01';form.append(node('p','muted','Пустая цена использует базовую. Персональная цена может быть ниже базовой.'));
  const free=node('input'),row=node('label','privacy-check');free.type='checkbox';row.append(free,node('span',null,'Выдать бесплатный доступ'));form.append(row);const until=inputField(form,'Бесплатный доступ до (необязательно)','date');until.min=today();panel.append(form);
  const save=node('button','fd-primary','Сохранить условия'),status=node('p','muted');save.type='submit';status.setAttribute('role','status');form.append(current,save,button('Вернуть базовые условия',async()=>{info=await post('admin/subscriptions',{member:member.value,reset:true});draw();status.textContent='Персональные условия убраны.';}),status);
  function selected(){return info.members.find(row=>row.id===member.value)?.subscription;}
  function draw(){const value=selected();cost.value=priceInputValue(value.personal_price);free.checked=value.free;until.value=value.free_until?new Date(value.free_until*1000).toLocaleDateString('sv-SE',{timeZone:'Europe/Moscow'}):'';until.disabled=!free.checked;current.textContent=value.mode==='personal_free'?'Назначен бесплатный доступ.':'Будущая цена: '+priceText(value.price);}
  free.onchange=()=>{until.disabled=!free.checked;};member.onchange=draw;draw();
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{info=await post('admin/subscriptions',{member:member.value,price:minorUnits(cost),free:free.checked,free_until:free.checked&&until.value?until.value:null});draw();status.textContent='Условия сохранены. Приём платежей отключён.';}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};
 });
}
