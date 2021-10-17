# this is a minimal test program which sends an email.  It is provided for testing purposes.
from smtplib import SMTP
import time

s = SMTP('localhost', 8025)
s.sendmail('foo@example.org', ['foo@example.org'], f"""\
From: foo@example.org
To: foo@example.org
Subject: A test from Arnie

I'll be back.
""")
s.quit()
