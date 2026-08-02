import urllib.request
import urllib.error
import zipfile
import tarfile
import os
import shutil
import sys

print("Detecting OS...")
is_windows = sys.platform.startswith('win')

if is_windows:
    print("Detected Windows")
    url = "https://github.com/official-stockfish/Stockfish/releases/download/sf_16.1/stockfish-windows-x86-64-avx2.zip"
    archive_path = "stockfish.zip"
else:
    print("Detected Linux / Mac (falling back to Ubuntu binary)")
    url = "https://github.com/official-stockfish/Stockfish/releases/download/sf_16.1/stockfish-ubuntu-x86-64-avx2.tar"
    archive_path = "stockfish.tar"

print(f"Downloading Stockfish from {url}...")
urllib.request.urlretrieve(url, archive_path)

print("Extracting Stockfish...")
if is_windows:
    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
        exe_name = next((name for name in zip_ref.namelist() if name.endswith(".exe")), None)
        if exe_name:
            print(f"Found executable: {exe_name}")
            zip_ref.extract(exe_name, ".")
            shutil.move(exe_name, "stockfish.exe")
            print("Moved to stockfish.exe")
        else:
            print("Could not find .exe in zip")
else:
    with tarfile.open(archive_path, 'r') as tar_ref:
        # find the binary file in the tar
        bin_member = None
        for member in tar_ref.getmembers():
            if member.isfile() and ("stockfish-ubuntu" in member.name or member.name.endswith("stockfish")):
                bin_member = member
                break
        
        if bin_member:
            print(f"Found executable: {bin_member.name}")
            f = tar_ref.extractfile(bin_member)
            if f:
                with open("stockfish", "wb") as out_f:
                    out_f.write(f.read())
                print("Moved to stockfish")
                # Give execute permissions
                os.chmod("stockfish", 0o755)
                print("Granted execute permissions (chmod +x)")
        else:
            print("Could not find binary in tar")


if os.path.exists(archive_path):
    os.remove(archive_path)
