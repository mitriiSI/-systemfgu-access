/* Keep touch feedback reliable on browsers that delay the native :active state. */
(() => {
 const host=document.getElementById('fgu-diary-design');
 let pressed=null,pointer=null;
 function release(){pressed?.classList.remove('is-pressing');pressed=null;pointer=null;}
 document.addEventListener('pointerdown',event=>{
  if(!event.isPrimary||event.button!==0)return;
  release();const control=event.target.closest('button,a.fd-primary,a.fd-secondary,summary,[role=button]');
  if(!control||!host.contains(control)||control.matches(':disabled,[aria-disabled=true]'))return;
  pressed=control;pointer=event.pointerId;control.classList.add('is-pressing');
 },true);
 for(const type of ['pointerup','pointercancel','lostpointercapture'])document.addEventListener(type,event=>{if(event.pointerId===pointer)release();},true);
 document.addEventListener('pointermove',event=>{
  if(!pressed||event.pointerId!==pointer)return;
  const box=pressed.getBoundingClientRect();
  if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)release();
 },true);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)release();});
 document.addEventListener('contextmenu',release,true);window.addEventListener('blur',release);
 const motion=matchMedia('(prefers-reduced-motion: reduce)'),animated=new Map();
 document.addEventListener('click',event=>{
  const control=event.target.closest('#nav button,#theme,#header-help,#logout');
  if(!control||!host.contains(control)||control.disabled||motion.matches)return;
  clearTimeout(animated.get(control));control.classList.remove('is-icon-animating');void control.offsetWidth;control.classList.add('is-icon-animating');
  animated.set(control,setTimeout(()=>{control.classList.remove('is-icon-animating');animated.delete(control);},750));
 },true);
 function stopAnimations(){for(const [control,timer] of animated){clearTimeout(timer);control.classList.remove('is-icon-animating');}animated.clear();}
 motion.addEventListener('change',()=>{if(motion.matches)stopAnimations();});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stopAnimations();});
})();
