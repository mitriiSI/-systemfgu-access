import unittest
from services.external_schedules import _geo_periods
from services.schedule_presentation import geography_label,subject_label


class GeographyTitlesTests(unittest.TestCase):
    def test_online_link_does_not_become_subject_or_room(self):
        periods=_geo_periods('Т О П О Г Р А Ф И Я (л) проф. Иванов И.И. 1234 https://my.mts-link.ru/j/14959509/26158090430','09:00','10:30')
        self.assertEqual(periods[0]['disciplineFullName'],'Топография')
        self.assertEqual(periods[0]['classroom'],'1234')
        self.assertEqual(periods[0]['teachersNameFull'],'Иванов И.И.')

    def test_link_inside_subject_does_not_remove_following_text(self):
        periods=_geo_periods('Социально-экономическая https://example.org/101 география 555','09:00','10:30')
        self.assertEqual(periods[0]['disciplineFullName'],'Социально-экономическая география')
        self.assertEqual(periods[0]['classroom'],'555')

    def test_dates_and_building_from_the_reported_cells(self):
        cases=[
            ('СОЦИАЛЬНО - ЭКОНОМИЧЕСКАЯ ГЕОГРАФИЯ, 8 октября','Социально-экономическая география',''),
            ('М А Т Е М А Т И К А 8 октября','Математика',''),
            ('ГЕОМОРФОЛОГИЯ С ОСНОВАМИ ГЕОЛОГИИ 9 октября','Геоморфология с основами геологии',''),
            ('РУССКИЙ ЯЗЫК И КУЛЬТУРА РЕЧИ 9 октября','Русский язык и культура речи',''),
            ('МАТЕМАТИКА 10 октября 02','Математика','02'),
            ('ФИЗИЧЕСКАЯ КУЛЬТУРА Трехзальный корпус','Физическая культура','Трехзальный корпус'),
        ]
        for raw,title,room in cases:
            with self.subTest(raw=raw):
                item=_geo_periods(raw,'09:00','10:35')[0]
                self.assertEqual(item['_diary_title'],title)
                self.assertEqual(item['classroom'],room)

    def test_numeric_dates_are_not_classrooms(self):
        item=_geo_periods('ГИДРОЛОГИЯ 09.10.2026 1708','09:00','10:35')[0]
        self.assertEqual(item['classroom'],'1708')
        self.assertEqual(item['_diary_title'],'Гидрология')

    def test_all_faculties_use_sentence_case_without_changing_saved_keys(self):
        self.assertEqual(subject_label('ИСТОРИЯ РОССИИ'),'История россии')
        self.assertEqual(subject_label('Английский Язык'),'Английский язык')
        self.assertEqual(geography_label('МАТЕМАТИКА 8 октября','02'),('Математика','02'))
