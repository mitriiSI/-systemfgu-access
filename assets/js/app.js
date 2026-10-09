(() => {
  'use strict';
  const data = window.SystemafguDemo;
  const root = document.getElementById('fgu-diary-design');
  const screen = document.getElementById('screen');
  const dialog = document.getElementById('lesson-dialog');
  const status = document.getElementById('status');
  const nav = document.getElementById('nav');
  const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
  const pages = ['day', 'teachers', 'materials', 'deadlines', 'profile'];
  let page = 'day';
  let materialFilter = 'all';
  let selectedDay = today();
  let toastTimer;
  let lastDialogTrigger;

  const storage = {
    get(key, fallback) {
      try { return JSON.parse(localStorage.getItem('systemafgu-' + key)) ?? fallback; }
      catch { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem('systemafgu-' + key, JSON.stringify(value)); return true; }
      catch { return false; }
    }
  };
  let notes = storage.get('notes', {});
  let done = storage.get('done', {});
  if (!notes || typeof notes !== 'object' || Array.isArray(notes)) notes = {};
  if (!done || typeof done !== 'object' || Array.isArray(done)) done = {};
  let faculty = storage.get('faculty', 'fgu');
  if (!Object.hasOwn(data.faculties, faculty)) faculty = 'fgu';

  function element(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined) result.textContent = text;
    return result;
  }
  function button(text, action, className = 'fd-secondary') {
    const result = element('button', className, text);
    result.type = 'button';
    result.addEventListener('click', action);
    return result;
  }
  function icon(name) {
    const paths = {
      left: 'm15 5-7 7 7 7', right: 'm9 5 7 7-7 7',
      calendar: 'M4 5h16v16H4z M8 3v4 M16 3v4 M4 10h16',
      room: 'M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z M12 7a3 3 0 1 0 0 6 3 3 0 1 0 0-6',
      check: 'm5 12 4 4L19 6', folder: 'M3 8V5h6l2 3h10v12H3z',
      close: 'm6 6 12 12 M6 18 18 6', moon: 'M20.5 14A8.6 8.6 0 0 1 10 3.5 8.6 8.6 0 1 0 20.5 14Z'
    };
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [key, value] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(key, value);
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', paths[name] || paths.calendar);
    svg.append(path);
    return svg;
  }
  function iconButton(name, label, action) {
    const result = button('', action, 'fd-icon-button');
    result.append(icon(name));
    result.setAttribute('aria-label', label);
    result.title = label;
    return result;
  }
  function dateObject(key) {
    const [year, month, day] = key.split('-').map(Number);
    return new Date(year, month - 1, day, 12);
  }
  function dateKey(value) {
    return [value.getFullYear(), String(value.getMonth() + 1).padStart(2, '0'), String(value.getDate()).padStart(2, '0')].join('-');
  }
  function today() {
    const parts = new Intl.DateTimeFormat('en', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  }
  function addDays(key, offset) {
    const date = dateObject(key);
    date.setDate(date.getDate() + offset);
    return dateKey(date);
  }
  function dateLabel(key, options = { day: 'numeric', month: 'long' }) {
    return dateObject(key).toLocaleDateString('ru-RU', options);
  }
  function toast(message) {
    clearTimeout(toastTimer);
    status.textContent = message;
    toastTimer = setTimeout(() => { status.textContent = ''; }, 5000);
  }
  function save(key, value) {
    const saved = storage.set(key, value);
    toast(saved ? 'Сохранено в этом браузере' : 'Изменения действуют до закрытия страницы: браузер запретил сохранение');
  }
  function teacherFor(lesson) { return data.teachers.find(teacher => teacher.id === lesson.teacher); }
  function noteFor(lesson) { return typeof notes[lesson.id] === 'string' ? notes[lesson.id] : lesson.homework; }

  function setTheme(theme) {
    root.dataset.theme = theme;
    document.documentElement.dataset.fguTheme = theme;
    document.documentElement.style.colorScheme = theme;
    document.documentElement.style.backgroundColor = theme === 'dark' ? '#080808' : '#f2f2f2';
    document.querySelector('meta[name="theme-color"]').content = theme === 'dark' ? '#080808' : '#f2f2f2';
    document.getElementById('theme').setAttribute('aria-label', theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему');
    try { localStorage.setItem('systemafgu-theme', theme); } catch { /* Optional preference. */ }
  }
  function applyFaculty() {
    const info = data.faculties[faculty];
    root.dataset.faculty = faculty;
    document.getElementById('faculty-title').textContent = info.name;
    document.getElementById('group-label').textContent = `${info.short} · ${info.group}`;
  }
  function navigate(next, focus = true) {
    page = pages.includes(next) ? next : 'day';
    root.dataset.page = page;
    for (const tab of nav.querySelectorAll('[data-page]')) {
      if (tab.dataset.page === page) tab.setAttribute('aria-current', 'page');
      else tab.removeAttribute('aria-current');
    }
    render();
    if (focus) {
      screen.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: 'instant' });
    }
  }
  function render() {
    const host = element('section', 'fd-detail-page' + (page === 'day' ? ' day-page' : ''));
    screen.replaceChildren(host);
    ({ day: renderDay, teachers: renderTeachers, materials: renderMaterials, deadlines: renderDeadlines, profile: renderProfile })[page](host);
  }
  function selectDay(key, focusDate = false) {
    selectedDay = key;
    render();
    if (focusDate) screen.querySelector(`[data-date="${key}"]`)?.focus({ preventScroll: true });
  }
  function renderDay(host) {
    host.append(element('p', 'eyebrow', selectedDay === today() ? 'СЕГОДНЯ' : 'РАСПИСАНИЕ'), element('h1', '', dateLabel(selectedDay, { weekday: 'long', day: 'numeric', month: 'long' })));
    const monday = addDays(selectedDay, -((dateObject(selectedDay).getDay() + 6) % 7));
    const tools = element('div', 'week-tools');
    const calendar = element('label', 'day-calendar-controls');
    calendar.append(icon('calendar'));
    const picker = element('input', 'demo-date-input');
    picker.type = 'date'; picker.value = selectedDay;
    picker.setAttribute('aria-label', 'Выбрать дату расписания');
    picker.addEventListener('change', () => { if (picker.value && picker.validity.valid) selectDay(picker.value); });
    calendar.append(picker);
    tools.append(iconButton('left', 'Предыдущий день', () => selectDay(addDays(selectedDay, -1))), calendar, iconButton('right', 'Следующий день', () => selectDay(addDays(selectedDay, 1))));
    const strip = element('div', 'week');
    strip.setAttribute('aria-label', 'Дни выбранной недели');
    for (let index = 0; index < 7; index++) {
      const key = addDays(monday, index);
      const cell = button('', () => selectDay(key, true), key === selectedDay ? 'active' : '');
      cell.dataset.date = key;
      cell.setAttribute('aria-label', dateLabel(key, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }));
      cell.setAttribute('aria-pressed', String(key === selectedDay));
      if (key === today()) cell.setAttribute('aria-current', 'date');
      cell.append(element('small', '', weekdays[index]), element('strong', '', String(dateObject(key).getDate())));
      cell.addEventListener('keydown', event => {
        const offset = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
        if (offset) { event.preventDefault(); selectDay(addDays(key, offset), true); }
      });
      strip.append(cell);
    }
    host.append(tools, strip);
    if (selectedDay !== today()) host.append(button('Вернуться к сегодня', () => selectDay(today()), 'fd-secondary day-return-today'));
    const lessons = data.lessons.filter(lesson => lesson.days.includes(dateObject(selectedDay).getDay()));
    const heading = element('div', 'section-heading');
    heading.append(element('h2', '', 'Пары'), element('span', 'lesson-count', lessons.length ? `${lessons.length} занятия` : 'Свободный день'));
    host.append(heading);
    if (!lessons.length) {
      const empty = element('div', 'empty-state');
      empty.append(icon('check'), element('h2', '', 'Сегодня без пар'), element('p', 'muted', 'Можно отдохнуть или подготовиться к следующей неделе.'));
      host.append(empty);
    }
    for (const lesson of lessons) {
      const card = element('article', 'fd-lesson-card');
      const meta = element('div', 'fd-lesson-meta');
      meta.append(element('time', '', `${lesson.start} — ${lesson.end}`), element('span', `lesson-badge ${lesson.kind}`, lesson.type));
      const title = button(lesson.title, event => openLesson(lesson, event.currentTarget), 'fd-lesson-name');
      const teacher = button(teacherFor(lesson).name, () => navigate('teachers'), 'fd-teacher-link');
      const room = element('div', 'fd-lesson-room');
      room.append(icon('room'), element('span', '', lesson.room));
      const note = noteFor(lesson);
      card.append(meta, title, teacher, room, element('p', 'homework-preview' + (note ? ' has-homework' : ''), note ? 'ДЗ · ' + note : 'Домашнее задание не задано'));
      host.append(card);
    }
  }
  function openLesson(lesson, trigger) {
    lastDialogTrigger = trigger;
    dialog.replaceChildren();
    const top = element('div', 'dialog-top');
    const title = element('h2', '', lesson.title);
    title.id = 'dialog-title';
    top.append(title, iconButton('close', 'Закрыть занятие', () => dialog.close()));
    const form = element('form', 'demo-homework-form');
    const label = element('label', 'fd-label', 'Домашнее задание');
    label.htmlFor = 'homework';
    const input = element('textarea', 'fd-input fd-textarea');
    input.id = 'homework'; input.name = 'homework'; input.maxLength = 4000; input.rows = 5; input.value = noteFor(lesson);
    const submit = element('button', 'fd-primary', 'Сохранить задание');
    submit.type = 'submit';
    form.append(label, input, element('p', 'muted', 'Задание сохранится в вашем браузере.'), submit);
    form.addEventListener('submit', event => {
      event.preventDefault(); notes[lesson.id] = input.value.trim();
      save('notes', notes); dialog.close(); render();
      screen.querySelector('.fd-lesson-name')?.focus({ preventScroll: true });
    });
    dialog.append(top, element('p', 'muted', `${lesson.start} — ${lesson.end} · ${lesson.room}`), element('p', 'muted', teacherFor(lesson).name), form);
    dialog.showModal();
  }
  function renderTeachers(host) {
    host.append(element('p', 'eyebrow', 'ВАША ГРУППА'), element('h1', '', 'Преподаватели'));
    for (const teacher of data.teachers) {
      const card = element('article', 'fd-lesson-card demo-teacher');
      card.append(element('span', 'identity-avatar', teacher.initials), element('h2', '', teacher.name), element('p', '', teacher.subject), element('p', 'muted', teacher.department));
      host.append(card);
    }
  }
  function renderMaterials(host) {
    host.append(element('p', 'eyebrow', 'ВСЁ ДЛЯ УЧЁБЫ'), element('h1', '', 'Учебные материалы'));
    const tabs = element('div', 'material-tabs');
    tabs.setAttribute('aria-label', 'Категории материалов');
    for (const [key, label] of [['all', 'Все файлы'], ['notes', 'Конспекты'], ['literature', 'Литература']]) {
      const tab = button(label, () => { materialFilter = key; render(); screen.querySelector(`[data-filter="${key}"]`)?.focus({ preventScroll: true }); }, materialFilter === key ? 'fd-primary' : 'fd-secondary');
      tab.dataset.filter = key;
      tab.setAttribute('aria-pressed', String(materialFilter === key));
      tabs.append(tab);
    }
    host.append(tabs);
    for (const item of data.materials.filter(item => materialFilter === 'all' || item.category === materialFilter)) {
      const row = element('a', 'unified-file');
      row.href = item.file;
      row.download = item.file.split('/').pop();
      const top = element('div', 'demo-file-heading');
      top.append(icon('folder'), element('strong', '', item.title));
      row.append(top, element('span', 'muted', item.subject), element('span', 'fd-file-metadata', item.label + ' · Скачать'));
      host.append(row);
    }
  }
  function renderDeadlines(host) {
    host.append(element('p', 'eyebrow', 'БЛИЖАЙШАЯ НЕДЕЛЯ'), element('h1', '', 'Дедлайны'));
    for (const item of data.deadlines) {
      const complete = done[item.id] === true;
      const card = element('article', 'fd-lesson-card demo-deadline' + (complete ? ' is-done' : ''));
      const due = addDays(today(), item.offset);
      card.append(element('span', 'lesson-badge', item.offset === 1 ? 'Завтра' : 'Через ' + item.offset + (item.offset < 5 ? ' дня' : ' дней')), element('h2', '', item.title), element('p', 'muted', item.subject), element('p', '', item.description));
      const time = element('time', 'muted', 'До ' + dateLabel(due) + ', 23:59 МСК');
      time.dateTime = due + 'T23:59:00+03:00';
      const label = element('label', 'demo-complete');
      const check = element('input'); check.type = 'checkbox'; check.checked = complete;
      const caption = element('span', '', complete ? 'Выполнено' : 'Отметить выполненным');
      check.addEventListener('change', () => {
        done[item.id] = check.checked;
        card.classList.toggle('is-done', check.checked);
        caption.textContent = check.checked ? 'Выполнено' : 'Отметить выполненным';
        save('done', done);
      });
      label.append(check, caption); card.append(time, label); host.append(card);
    }
  }
  function renderProfile(host) {
    host.append(element('p', 'eyebrow', 'ДЕМО-СТУДЕНТ'), element('h1', '', 'Настройки'));
    const panel = element('section', 'fd-lesson-card demo-settings');
    const label = element('label', 'fd-label', 'Факультет'); label.htmlFor = 'faculty-select';
    const select = element('select', 'fd-input'); select.id = 'faculty-select';
    for (const [key, info] of Object.entries(data.faculties)) {
      const option = element('option', '', info.name); option.value = key; select.append(option);
    }
    select.value = faculty;
    select.addEventListener('change', () => { faculty = select.value; applyFaculty(); save('faculty', faculty); });
    panel.append(label, select, element('p', 'muted', 'Меняется оформление факультета. В демонстрации используется общее примерное расписание.'));
    host.append(panel);
  }

  dialog.addEventListener('close', () => { if (lastDialogTrigger?.isConnected) lastDialogTrigger.focus({ preventScroll: true }); });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
  document.getElementById('theme').addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));
  document.getElementById('back').addEventListener('click', () => { selectedDay = today(); navigate('day'); });
  document.getElementById('profile').addEventListener('click', () => navigate('profile'));
  nav.addEventListener('click', event => {
    const tab = event.target.closest('[data-page]');
    if (tab && nav.contains(tab)) navigate(tab.dataset.page);
  });
  applyFaculty();
  setTheme(document.documentElement.dataset.fguTheme || 'dark');
  navigate('day', false);
})();
