with open('requirements.txt', 'rb') as f:
    c = f.read()
c = c.replace(b'\x00', b'')
with open('requirements.txt', 'wb') as f:
    f.write(c)
