// Keep the browser open while the user confirms their identity in the bot.
function reserveMessengerTab(){try{const tab=window.open('about:blank','_blank');if(tab)tab.opener=null;return tab;}catch{return null;}}
function messengerUrl(value){const target=new URL(value);if(target.protocol!=='https:'||!['t.me','max.ru'].includes(target.hostname))throw Error('Не удалось открыть бота.');return target.href;}
function launchMessenger(tab,url){url=messengerUrl(url);if(tab&&!tab.closed)tab.location.replace(url);else location.assign(url);}
function pendingMessenger(value){try{if(value)sessionStorage.setItem('midiary-pending-login',JSON.stringify(value));else sessionStorage.removeItem('midiary-pending-login');}catch{}}
function confirmMaxBrowserRequest(result){
 const token=result.browser_confirmation?.token;if(!token)return;
 const dialog=node('dialog','subject-teachers-dialog'),status=node('p','muted');status.setAttribute('role','status');dialog.setAttribute('aria-label','Подтверждение входа');
 dialog.append(node('h2',null,'Подтвердить вход в браузере?'),node('p',null,'Нажмите подтверждение, только если сами начали вход на сайте Midiary. После подтверждения вернитесь в свой браузер.'));
 const approve=button('Подтвердить вход',()=>submit(true),'fd-primary'),deny=button('Отклонить',()=>submit(false));
 async function submit(value){approve.disabled=deny.disabled=true;try{await post('max/browser/confirm',{token,approve:value});dialog.close();}catch(error){status.textContent=error.message;}finally{approve.disabled=deny.disabled=false;}}
 dialog.append(approve,deny,status);root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();approve.focus();
}
async function pollMessengerLogin(platform,host,request={expires_in:300}){
 const generation=++loginGeneration,panel=node('section',platform+'-login-request'),status=node('p','muted',platform==='max'?'Откройте дневник внутри MAX и подтвердите вход в браузере. Эта страница войдёт автоматически.':'Подтвердите вход в боте. Эта страница войдёт автоматически.');
 host.querySelectorAll('.telegram-login-request,.max-login-request').forEach(previous=>previous.remove());
 const until=request.until||Date.now()+request.expires_in*1000;
 let timer,inFlight=false,stopped=false;
 function stop(){stopped=true;clearTimeout(timer);window.removeEventListener('focus',wake);document.removeEventListener('visibilitychange',wake);}
 function wake(){if(!document.hidden&&!stopped){clearTimeout(timer);poll();}}
 panel.append(status);
 if(request.url){const link=node('a','fd-secondary',platform==='max'?'Открыть дневник в MAX':'Открыть бота ещё раз');link.href=messengerUrl(request.url);link.target='_blank';link.rel='noopener';panel.append(link);}
 panel.append(button('Отмена',()=>{stop();loginGeneration++;pendingMessenger('');panel.remove();}));host.append(panel);
 pendingMessenger({platform,until,url:request.url||''});
 window.addEventListener('focus',wake);document.addEventListener('visibilitychange',wake);
 async function poll(){
  if(stopped||inFlight)return;
  if(generation!==loginGeneration||!panel.isConnected){stop();return;}
  if(Date.now()>until){status.textContent='Запрос истёк. Начните вход заново.';pendingMessenger('');stop();return;}
  inFlight=true;
  try{
   const result=await post(platform==='max'?'max/browser/poll':'browser/poll',{});
   if(generation!==loginGeneration||!panel.isConnected){stop();return;}
   if(result.ok){pendingMessenger('');stop();await enterBrowser(result);return;}
   if(result.needs_code)status.textContent=platform==='max'?'Свяжите аккаунт по Telegram ID в боте MAX или зарегистрируйтесь там по коду администратора.':'Завершите регистрацию в боте Telegram по коду или разрешению администратора для вашего ID.';
   else if(['denied','expired'].includes(result.status)){status.textContent=result.status==='denied'?'Вход отклонён.':'Запрос истёк. Начните вход заново.';pendingMessenger('');stop();return;}
  }catch(error){status.textContent=error.message;if(error.status===403){pendingMessenger('');stop();}}
  finally{inFlight=false;if(!stopped)timer=setTimeout(poll,1600);}
 }
 poll();
}
async function beginMessengerLogin(platform,host){
 const control=host.querySelector('.'+platform+'-login');if(control?.disabled)return;if(control)control.disabled=true;
 const native=platform==='max'?maxInitData():tg?.initData;
 const tab=native?null:reserveMessengerTab();
 try{
  if(native){
   try{const result=await post(platform==='max'?'max/auth':'auth',{initData:native});if(!result.needs_code){await enterBrowser(result);if(platform==='max')confirmMaxBrowserRequest(result);return;}}
   catch(error){if(error.status!==401)throw error;}
  }
  const request=await post(platform==='max'?'max/browser/start':'browser/start',{});
  await pollMessengerLogin(platform,host,request);launchMessenger(tab,request.url);
 }catch(error){if(tab&&!tab.closed)tab.close();throw error;}
 finally{if(control)control.disabled=false;}
}
function beginTelegramLogin(host){return beginMessengerLogin('telegram',host);}
function beginMaxLogin(host){return beginMessengerLogin('max',host);}
async function beginBotRegistration(platform){
 const tab=reserveMessengerTab();try{const info=await api('bots/info');launchMessenger(tab,info[platform]+'?start=register_'+uiLanguage());}catch(error){if(tab&&!tab.closed)tab.close();throw error;}
}
function resumeMessengerLogin(host){
 let saved;try{const raw=sessionStorage.getItem('midiary-pending-login');if(!raw)return;saved=['telegram','max'].includes(raw)?{platform:raw,expires_in:300}:JSON.parse(raw);if(typeof saved==='string')saved={platform:saved,expires_in:300};}catch{pendingMessenger('');return;}
 if(['telegram','max'].includes(saved?.platform))pollMessengerLogin(saved.platform,host,saved);
}
