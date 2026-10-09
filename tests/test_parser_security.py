"""Real parser isolation and bounded archive/XML abuse cases."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from services.table_schedules import docx_grids, _zip
from services.parser_sandbox import parse_timetable


class ParserSecurityTests(unittest.TestCase):
    def test_busy_parser_rejects_extra_work_before_spawning(self):
        from services import parser_sandbox
        self.assertTrue(parser_sandbox._slots.acquire(blocking=False))
        try:
            with patch('services.parser_sandbox.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(ValueError,'занято'):
                    parse_timetable(b'fake','test.pdf',{},'101')
                spawn.assert_not_called()
        finally:
            parser_sandbox._slots.release()

    def test_word_entities_are_rejected(self):
        xml = b'<!DOCTYPE x [<!ENTITY secret "sensitive">]><x>&secret;</x>'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as book:
            book.writestr('word/document.xml', xml)
        with self.assertRaises(ValueError):
            docx_grids(buffer.getvalue())

    def test_compressed_archive_cannot_expand_past_limit(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as book:
            book.writestr('word/document.xml', b'0' * (40 * 1024 * 1024 + 1))
        self.assertLess(len(buffer.getvalue()), 100000)
        with self.assertRaises(ValueError):
            _zip(buffer.getvalue())

    def test_real_worker_drops_privileges_blocks_network_and_cannot_read_private_file(self):
        if os.geteuid() != 0:
            self.skipTest('Container privilege separation is checked as root')
        with tempfile.TemporaryDirectory() as directory:
            secret=Path(directory)/'private.txt';secret.write_text('fake confidential data');secret.chmod(0o600)
            source = "import sys,json,socket,os;sys.path.insert(0," + repr(str(Path(__file__).resolve().parents[1])) + ");from services.parser_worker import restrict;restrict(62001);r={'uid':os.geteuid()};\n"
            source += "try: socket.socket();r['network_blocked']=False\nexcept PermissionError: r['network_blocked']=True\n"
            source += "try: open(" + repr(str(secret)) + ").read();r['private_file_blocked']=False\nexcept PermissionError: r['private_file_blocked']=True\n"
            source += "print(json.dumps(r))"
            result=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,timeout=10,env={'PATH':'/usr/bin:/bin'})
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        self.assertNotEqual(value['uid'],0)
        self.assertTrue(value['network_blocked'])
        self.assertTrue(value['private_file_blocked'])

    def test_worker_receives_no_site_credentials_and_still_reads_real_pdf(self):
        data=(Path(__file__).parent/'fixtures'/'fgp-first-course.pdf').read_bytes()
        original=subprocess.Popen
        with patch('services.parser_sandbox.subprocess.Popen',wraps=original) as spawn:
            value=parse_timetable(data,'fgp.pdf',{},'101')
        self.assertFalse(value['errors'])
        self.assertTrue(value['rows'])
        environment=spawn.call_args.kwargs['env']
        for name in ('BOT_TOKEN','SESSION_SECRET','MAX_BOT_TOKEN','SUPPORT_BOT_TOKEN','HTTP_PROXY','HTTPS_PROXY'):
            self.assertNotIn(name,environment)
