// MAX is an optional host for the same diary; startup never waits for its CDN in a browser.
const maxLaunchFields=new URLSearchParams(location.hash.slice(1)),maxLaunchValues=maxLaunchFields.getAll('WebAppData');
const maxLaunchData=maxLaunchValues.length===1?maxLaunchValues[0]:'';
function maxInitData(){
 const raw=window.WebApp?.initData;if(typeof raw==='string'&&raw)return raw;
 return maxLaunchData;
}
function inMax(){return !!maxInitData();}
function maxRegistrationLaunch(){return new URLSearchParams(maxInitData()).get('start_param')==='register';}
let maxBridgePromise=null;
function maxBridge(){
 if(window.WebApp?.downloadFile)return Promise.resolve(window.WebApp);
 if(!inMax())return Promise.resolve(null);
 if(!maxBridgePromise)maxBridgePromise=new Promise(resolve=>{
  const script=document.createElement('script');script.src='https://st.max.ru/js/max-web-app.js';script.async=true;
  const timer=setTimeout(()=>resolve(null),6000);script.onload=()=>{clearTimeout(timer);resolve(window.WebApp||null);};script.onerror=()=>{clearTimeout(timer);resolve(null);};document.head.append(script);
 });return maxBridgePromise;
}
if(inMax())maxBridge();

async function maxAccountSection(host){
 const section=node('section','max-account'),status=node('p','muted');status.setAttribute('role','status');section.append(node('h2',null,'Аккаунт MAX'),status);host.append(section);
 try{
  const result=await api('max/account');if(!host.isConnected)return;
  status.textContent=result.linked?'MAX подключён. Данные и права общие с Telegram.':'Для подключения откройте бота MAX и отправьте /link с кодом доступа Midiary.';
  const link=node('a','fd-secondary','Открыть бота MAX');link.href=result.bot_url;link.target='_blank';link.rel='noopener';section.append(link);
  if(!result.linked&&maxInitData())section.append(button('Подключить этот аккаунт MAX',async()=>{await post('max/account',{initData:maxInitData()});await go('profile',false);}));
  if(result.linked)section.append(button('Отключить MAX',async()=>{await api('max/account',{method:'DELETE'});await go('profile',false);}));
 }catch(error){status.textContent=error.message;}
}
