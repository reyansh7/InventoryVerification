import urllib.request
import bz2
import os

url = "http://ciscobinary.openh264.org/openh264-1.8.0-win64.dll.bz2"
output_filename = "openh264-1.8.0-win64.dll"

print("Downloading OpenH264 DLL...")
req = urllib.request.urlopen(url)
compressed_data = req.read()

print("Decompressing...")
uncompressed_data = bz2.decompress(compressed_data)

with open(output_filename, 'wb') as f:
    f.write(uncompressed_data)

print(f"Done! Saved to {os.path.abspath(output_filename)}")
