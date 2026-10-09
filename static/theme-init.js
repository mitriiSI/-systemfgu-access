(function(){
  let saved;
  try{saved=localStorage.getItem('fgu-theme');}catch{}
  const theme=['light','dark'].includes(saved)?saved:'dark';
  document.documentElement.dataset.fguTheme=theme;
  document.documentElement.style.colorScheme=theme;
  document.documentElement.style.backgroundColor=theme==='dark'?'#080808':'#f4f4f5';
})();
