/* Fictional fixtures. No production users, timetable exports or API credentials. */
window.SystemafguDemo = {
  faculties: {
    fgu: { name: 'Факультет государственного управления', short: 'ФГУ', group: '107пб' },
    geo: { name: 'Географический факультет', short: 'Геофак', group: '101' },
    ffl: { name: 'Факультет иностранных языков и регионоведения', short: 'ФИЯР', group: '102' },
    fgp: { name: 'Факультет глобальных процессов', short: 'ФГП', group: '103' }
  },
  teachers: [
    { id: 'smirnov', name: 'Алексей Смирнов', initials: 'АС', subject: 'Теория государственного управления', department: 'Кафедра государственного управления' },
    { id: 'sokolova', name: 'Мария Соколова', initials: 'МС', subject: 'Экономика', department: 'Кафедра экономики' },
    { id: 'volkov', name: 'Иван Волков', initials: 'ИВ', subject: 'Иностранный язык', department: 'Кафедра иностранных языков' }
  ],
  lessons: [
    { id: 'governance', title: 'Теория государственного управления', teacher: 'smirnov', type: 'Лекция', kind: 'lecture', room: 'Аудитория 302', start: '09:00', end: '10:30', days: [1, 3, 5], homework: 'Прочитать главу 2 и выписать основные функции государственного управления.' },
    { id: 'economics', title: 'Экономика', teacher: 'sokolova', type: 'Семинар', kind: 'seminar', room: 'Аудитория 215', start: '10:45', end: '12:15', days: [1, 2, 4, 5], homework: 'Решить задачи 1–3 по теме «Спрос и предложение».' },
    { id: 'language', title: 'Иностранный язык', teacher: 'volkov', type: 'Практика', kind: 'practice', room: 'Аудитория 118', start: '13:00', end: '14:30', days: [2, 3, 4, 5], homework: 'Подготовить короткое выступление о выбранной стране.' }
  ],
  materials: [
    { id: 'lecture-notes', title: 'Функции государственного управления', subject: 'Теория государственного управления', category: 'notes', label: 'Конспект · Markdown', file: 'assets/materials/governance.md' },
    { id: 'economics-notes', title: 'Спрос и предложение', subject: 'Экономика', category: 'notes', label: 'Конспект · Markdown', file: 'assets/materials/economics.md' },
    { id: 'reading-list', title: 'Список тем для самостоятельной подготовки', subject: 'Учебная литература', category: 'literature', label: 'План чтения · Markdown', file: 'assets/materials/reading-list.md' }
  ],
  deadlines: [
    { id: 'economics-task', title: 'Задачи по экономике', subject: 'Экономика', offset: 1, description: 'Решить задачи 1–3 и записать ход решения.' },
    { id: 'governance-essay', title: 'Эссе о государственном управлении', subject: 'Теория государственного управления', offset: 3, description: 'Выбрать одну функцию управления и привести пример её применения.' },
    { id: 'language-talk', title: 'Выступление на иностранном языке', subject: 'Иностранный язык', offset: 6, description: 'Подготовить выступление на 3–5 минут.' }
  ]
};
