# Identifikasi Suara Herpetofauna Tanah Papua

Aplikasi web untuk rekaman AudioMoth (PAR001–PAR024): menyaring rekaman dengan pipeline
tervalidasi, mendeteksi aktivitas di pita katak 2,4–3,8 kHz, lalu mengenali suara katak dengan
**embedding Google Perch v2 + klasifier kecil yang dilatih dari label Anda sendiri**.

## Kenapa Perch + klasifier sendiri?

- Perch v2 (Google DeepMind) dilatih pada burung, katak, serangga dan mamalia; embedding 1.536
  dimensinya bagus untuk spesies yang tidak dikenalnya. Uji pada 33 rekaman iNaturalist dari 10
  spesies katak Papua: regresi logistik di atas embedding Perch benar **73%** (leave-one-out,
  tebakan acak 21%), padahal label langsung Perch hampir selalu salah (spesies Amerika/Asia).
- BirdNET hanya sebagai pembanding; cakupan katak Papua-nya sangat minim.
- Jadi skor "Perch langsung" di aplikasi hanya pembanding. Identifikasi spesies berasal dari
  **model kustom** yang Anda latih dengan memberi label pada jendela 5 detik.

## Alur kerja

1. **Analisis**: unggah file (WAV/FLAC/MP3/M4A/OGG) atau coba *rekaman contoh sintetis*.
   Aplikasi membaca jam dari nama `YYYYMMDD_HHMMSS.WAV` dan folder `PARxxx`, menandai apakah
   masuk jendela 17:30–21:00 WIT, lalu menjalankan:
   - highpass 2.100 Hz ×2 + lowpass 8.000 Hz ×2;
   - deteksi puncak nada sempit per file (FFT rata-rata) di luar pita katak, tanpa frekuensi
     hardcode;
   - notch bertingkat per puncak (−50/−45/−40 dB, lebar 5/12/25 Hz) yang meredam pita katak < 1 dB;
   - normalisasi puncak ke −2 dBFS, keluaran 48 kHz PCM 16-bit;
   - verifikasi level per pita sebelum/sesudah dan spektrogram sebelum/sesudah.
   - Tidak memakai teknik yang gagal di catatan: afftdn/anlmdn, spectral subtraction,
     bandreject statis, loudnorm.
2. **Label**: tiap jendela 5 detik bisa diberi nama spesies (atau `bukan katak`, `hujan`, dll.).
3. **Latih**: tab *Model & label* → *Latih model*. Butuh ≥ 2 kelas; akurasi validasi silang
   muncul bila tiap kelas punya ≥ 2 contoh. Setelah itu kolom *Model kustom* terisi untuk setiap
   rekaman. Label bisa diekspor ke CSV.

## Menjalankan di komputer sendiri (Mac/Windows/Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn suarakatak.server:app --port 8000
# buka http://localhost:8000
```

Model Perch v2 (~400 MB) diunduh otomatis dari Kaggle saat analisis pertama. Untuk komputer
tanpa internet, unduh sekali lalu set `PERCH_PATH=/folder/perch_v2_cpu`. Data aplikasi
(rekaman, label, model) tersimpan di `~/.suarakatak` (ubah dengan `SUARAKATAK_DATA`).
`ffmpeg` diperlukan untuk MP3/M4A.

## Memproses seluruh hardisk (batch)

```bash
python -m suarakatak.batch --masukan "I:/PAR" --keluaran "I:/HASIL_EKSTRAKSI/HASIL" --batas 20   # uji 20 file
python -m suarakatak.batch --masukan "I:/PAR" --keluaran "I:/HASIL_EKSTRAKSI/HASIL" --perch      # semua
```

Hanya file 17:30–21:00 (ubah dengan `--jam`). Hasil: `HASIL/<PAR>/<tanggal>/*.WAV` + `CONFIG.TXT`,
`ringkasan.csv` (nada yang di-notch, level pita, % aktif pita katak) dan
`embedding/<PAR>/*.npz` dengan `--perch`. Kolom `tebakan_perch_belum_terverifikasi`
berisi tebakan model global, **bukan identifikasi spesies yang diverifikasi**. `status=ok`
hanya berarti pemrosesan berhasil. Perch batch memakai audio keluaran terfilter.

Ganti jalur contoh dengan lokasi hardisk Anda (Linux, misalnya `--masukan /media/anda/PAR`).
Folder masukan yang tidak ada menghasilkan galat; bila tidak ada WAV/FLAC dalam jendela waktu,
pesan menyatakannya secara eksplisit. CONFIG.TXT disalin, bukan dibaca untuk koreksi zona waktu;
jam pada nama file dianggap sudah waktu lokal WIT.

Tekan Ctrl-C untuk berhenti, lalu jalankan kembali **perintah yang sama** untuk melanjutkan.
WAV dan embedding ditulis melalui file sementara lalu diganti secara atomik.
CSV dipadatkan secara atomik saat mulai dan selesai (juga saat Ctrl-C); selama proses,
satu baris ditambahkan dan di-flush per file. Bila proses terputus paksa, baris terakhir
per file berlaku dan duplikasi dibersihkan saat mulai lagi, tanpa menulis ulang seluruh CSV per file.
Hasil dilewati hanya bila WAV dan baris CSV sukses sudah ada (serta embedding dan tebakan
bila memakai `--perch`). WAV yang sudah ada dipakai kembali untuk melengkapi hasil yang kurang;
ringkasan penyaringan yang belum tercatat dihitung ulang dari sumber, tanpa menimpa WAV yang valid.
Karena itu rekaman sumber tetap perlu tersedia. Uji `--batas 20` tanpa Perch lalu menjalankan
`--perch` pada folder keluaran yang sama juga melengkapi embedding file uji.
File gagal dicoba ulang; CSV menyimpan satu baris terbaru per file, bukan duplikasi kegagalan.
CSV format lama dibaca dan kolom tebakan diganti otomatis. Kode keluar: 0 normal (termasuk
tidak ada file baru), 1 ada file gagal, 2 folder masukan tidak ditemukan, 130 dihentikan Ctrl-C.
Jangan jalankan dua proses batch sekaligus pada folder keluaran yang sama.

## Struktur

| File | Isi |
|---|---|
| `suarakatak/pipeline.py` | penyaringan adaptif + verifikasi level pita |
| `suarakatak/deteksi.py` | segmen aktif di pita katak |
| `suarakatak/perch.py` | Perch v2: embedding, label amfibi (1.352 dari 14.795) |
| `suarakatak/klasifikasi.py` | SQLite label + regresi logistik |
| `suarakatak/server.py`, `static/` | aplikasi web FastAPI |
| `suarakatak/batch.py` | pemrosesan massal |
| `scripts/buat_label_amfibi.py` | menyusun ulang daftar label amfibi Perch (GBIF Amphibia) |

Uji: `pip install pytest && pytest`.

Rekaman contoh sintetis hanya meniru profil gangguan PAR001 dan pulsa ~2.940 Hz; bukan suara katak asli.
