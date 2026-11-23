const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 1) => (n == null ? "–" : Number(n).toLocaleString("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d }));
// Dibulatkan ke bawah agar skor beberapa kelas tidak berjumlah lebih dari 100%.
const persenSkor = (s) => (s > 0 && s < 0.01 ? "<1%" : `${Math.floor(s * 100 + 1e-9)}%`);
let aktifId = null;
let semuaLabel = [];
let jumlahLabel = {};
let infoModel = {};

function peringatanModel() {
  const jumlah = Object.values(jumlahLabel);
  if (jumlah.length < 2 || jumlah.some((n) => n < 10) || infoModel.data_kecil) {
    return 'Hasil belum dapat diandalkan. Tambahkan sedikitnya 10 label yang sudah diperiksa untuk setiap kelompok, diambil dari sedikitnya 3 rekaman berbeda. Jika hasil belum diuji dengan contoh lain, ketepatannya belum diketahui. Semua tebakan tetap perlu diperiksa ahli.';
  }
  return infoModel.siap && !infoModel.usang && infoModel.akurasi_cv != null
    ? 'Semua tebakan belum diverifikasi. Persentase tinggi bukan bukti bahwa jenisnya benar; mintalah pemeriksaan ahli.'
    : 'Hasil belum dapat diandalkan. Label mungkin sudah berubah atau hasil uji belum tersedia. Tambahkan contoh dari rekaman berbeda untuk setiap kelompok, lalu pilih Latih model. Semua tebakan tetap perlu diperiksa ahli.';
}

function pesanError(status, detail) {
  const pesan = ({
    413: "File terlalu besar. Pilih rekaman yang lebih kecil atau potong menjadi beberapa bagian.",
    500: "Server gagal memproses rekaman. Coba lagi nanti.",
    502: "Server sedang sibuk atau tidak merespons. Coba lagi nanti.",
    503: "Server sedang sibuk atau tidak merespons. Coba lagi nanti.",
    504: "Server terlalu lama merespons. Coba lagi nanti atau gunakan rekaman lebih pendek.",
  })[status] || "Permintaan gagal. Periksa file dan coba lagi.";
  return status < 500 && typeof detail === "string" && detail.trim() ? detail : pesan;
}

async function api(url, opt) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15 * 60 * 1000);
  try {
    const r = await fetch(url, { credentials: "same-origin", ...opt, signal: controller.signal });
    if (!r.ok) {
      let detail;
      try { detail = (await r.json()).detail; } catch (_) {}
      throw new Error(pesanError(r.status, detail));
    }
    return await r.json();
  } catch (e) {
    if (controller.signal.aborted) throw new Error("Analisis melebihi batas waktu 15 menit. Coba rekaman yang lebih pendek.");
    if (e instanceof TypeError) throw new Error("Tidak dapat terhubung ke server. Periksa koneksi internet lalu coba lagi.");
    if (e instanceof SyntaxError) throw new Error("Balasan server tidak bisa dibaca. Coba lagi nanti.");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => {
      x.classList.toggle("aktif", x === b);
      if (x === b) x.setAttribute("aria-current", "page");
      else x.removeAttribute("aria-current");
    });
    $("#judul-tab").textContent = b.textContent.replace(/[▥⌘≋◈▤↗]/g, "").trim();
    document.querySelectorAll("main > section").forEach((s) => (s.hidden = s.id !== "tab-" + b.dataset.tab));
    if (b.dataset.tab === "model") muatModel();
    if (b.dataset.tab === "pola") muatPola().catch((e) => ($("#daftar-templat").innerHTML = `<p class="status-warn">${esc(e.message)}</p>`));
    if (b.dataset.tab === "soundscape") muatSitusSoundscape();
  })
);

async function muatStatus() {
  const s = await api("/api/status");
  $("#versi").textContent = s.versi;
  semuaLabel = Object.keys(s.label);
  jumlahLabel = s.label;
  infoModel = s.model;
  return s;
}

async function muatDaftar() {
  const rows = await api("/api/rekaman");
  $("#jumlah-rekaman").textContent = `${rows.length} rekaman`;
  const ul = $("#daftar");
  ul.innerHTML = rows.length ? "" : '<li class="muted">Belum ada rekaman.</li>';
  $("#cara-pakai").hidden = rows.length > 0;
  for (const r of rows) {
    const li = document.createElement("li");
    li.className = r.id === aktifId ? "aktif" : "";
    li.innerHTML = `<div class="nama">${esc(r.nama_file)}</div><div class="muted">${r.jendela} jendela · ${r.dilabel} dilabel</div>`;
    li.onclick = () => buka(r.id);
    ul.appendChild(li);
  }
}

function saran(list) {
  if (!list || !list.length) return '<span class="muted">–</span>';
  return `<div class="saran">${list.map((p) => `<div>${esc(p.label.replace(/_/g, " "))} <span class="muted mono">${persenSkor(p.skor)}</span></div>`).join("")}</div>`;
}

function statusModel(r) {
  if (!r.siap) return '<p class="status-warn">Belum ada model terlatih. Beri label sedikitnya dua kelompok berbeda, lalu pilih Latih model.</p>';
  return `<p class="${r.usang ? "status-warn" : "muted"}">${r.usang ? "Label berubah sejak latihan terakhir. Pilih Latih model lagi. " : ""}Terakhir dilatih: ${esc(r.dilatih_pada)} · ${r.n} label dalam ${Object.keys(r.kelas).length} kelompok.</p>
    <p class="status-warn">Semua tebakan belum diverifikasi. Persentase bukan kepastian jenis.${r.data_kecil ? " Contoh masih sedikit; hasil belum dapat diandalkan." : ""}</p>
    <p class="muted">Hasil uji dengan rekaman terpisah: ${r.akurasi_cv == null ? "belum tersedia. Tambahkan contoh dari rekaman berbeda untuk setiap kelompok." : fmt(r.akurasi_cv * 100, 0) + "% cocok. Ini bukan jaminan untuk rekaman baru."}</p>`;
}

function tabelLevel(d) {
  const p = d.penyaringan;
  return `<table class="tabel"><thead><tr><th>Pita</th><th class="angka">Rata² sebelum</th><th class="angka">Rata² sesudah</th><th class="angka">Perubahan</th></tr></thead><tbody>${Object.keys(p.level_sebelum)
    .map((k) => {
      const a = p.level_sebelum[k].mean_db, b = p.level_sesudah[k].mean_db;
      if (a == null || b == null) return `<tr><td>${esc(k)}</td><td colspan="3">Tidak bisa dinilai: laju sampel terlalu rendah.</td></tr>`;
      const senyapA = p.level_sebelum[k].senyap || a <= -150;
      const senyapB = p.level_sesudah[k].senyap || b <= -150;
      return `<tr><td>${esc(k)}</td><td class="angka">${senyapA ? "senyap" : `${fmt(a)} dB`}</td><td class="angka">${senyapB ? "senyap" : `${fmt(b)} dB`}</td><td class="angka">${senyapA || senyapB ? "–" : `${fmt(b - a)} dB`}</td></tr>`;
    })
    .join("")}</tbody></table>`;
}

async function buka(id) {
  aktifId = id;
  muatDaftar();
  const d = await api(`/api/rekaman/${id}`);
  await muatStatus();
  const am = d.audiomoth;
  const jendela =
    am.dalam_jendela_1730_2100 == null
      ? '<span class="muted">nama file bukan format AudioMoth</span>'
      : am.dalam_jendela_1730_2100
      ? '<span class="status-ok">dalam jendela 17:30–21:00</span>'
      : '<span class="status-warn">di luar jendela 17:30–21:00</span>';
  const puncak = d.penyaringan.puncak_dinotch;
  const adaMulai = d.jendela.length > 0;
  const pita = d.mode_rendah ? "0,5–3,8 kHz" : "2,4–3,8 kHz";
  const namaAsli = d.nama_file.split(/[\\/]/).pop().replace(/ \([^)]*\)$/, "");
  const namaDibersihkan = namaAsli.replace(/\.[^.]+$/, "") + "-dibersihkan.wav";
  $("#detail").innerHTML = `
    <div class="baris" style="justify-content:space-between">
      <h2 style="margin:0;word-break:break-all">${esc(d.nama_file)}</h2>
      <button class="tombol kecil" id="tombol-hapus">Hapus</button>
    </div>
    ${(d.peringatan || []).map((pesan) => `<p class="status-warn">${esc(pesan)}</p>`).join("")}
    <div class="info">
      <span><b>Durasi</b> ${fmt(d.durasi_s)} dtk</span>
      <span><b>Sample rate</b> ${d.sample_rate_asli} Hz</span>
      <span><b>Mode</b> ${d.mode_rendah ? "Frekuensi rendah · highpass 400 Hz · bukan metode tervalidasi" : "Standar · highpass 2100 Hz"}</span>
      ${am.waktu ? `<span><b>Waktu</b> ${esc(am.waktu)} WIT</span>` : ""}
      ${!am.waktu && am.tanggal ? `<span><b>Tanggal</b> ${esc(am.tanggal)} (jam tidak diketahui)</span>` : ""}
      ${am.par ? `<span><b>Lokasi</b> ${esc(am.par)}</span>` : ""}
      <span>${jendela}</span>
      <span><b>Aktivitas pita ${pita}</b> ${fmt(d.aktivitas.detik_aktif)} dtk (${fmt(d.aktivitas.persen_aktif)}%), ${d.aktivitas.jumlah_segmen} segmen</span>
    </div>
    <div class="dua">
      <div><div class="muted">Asli</div><audio id="audio-asli" controls preload="metadata" src="/api/rekaman/${id}/audio/asli"></audio>
        <a class="tombol unduh-audio" href="/api/rekaman/${id}/audio/asli" download="${esc(namaAsli)}">Unduh rekaman asli</a>
        <div class="gulir gambar-lebar"><img class="spek" src="/api/rekaman/${id}/spektrogram/sebelum.png" alt="Spektrogram sebelum"></div>
        <a class="buka-penuh" href="/api/rekaman/${id}/spektrogram/sebelum.png" target="_blank" rel="noopener">Buka ukuran penuh ↗</a></div>
      <div><div class="muted">Suara yang dibersihkan</div><audio id="audio-terfilter" controls preload="metadata" src="/api/rekaman/${id}/audio/terfilter"></audio>
        <a class="tombol unduh-audio" href="/api/rekaman/${id}/audio/terfilter" download="${esc(namaDibersihkan)}">Unduh suara yang dibersihkan</a>
        <div class="gulir gambar-lebar"><img class="spek" src="/api/rekaman/${id}/spektrogram/sesudah.png" alt="Spektrogram sesudah"></div>
        <a class="buka-penuh" href="/api/rekaman/${id}/spektrogram/sesudah.png" target="_blank" rel="noopener">Buka ukuran penuh ↗</a></div>
    </div>
    <h3>Kehadiran tervalidasi manual</h3>
    <p>${(d.hadir_tervalidasi || []).length ? d.hadir_tervalidasi.map((h) => `<span class="lencana hadir">${esc(h.spesies)} · ${h.n} deteksi</span>`).join(" ") : '<span class="muted">Belum ada jenis yang divalidasi hadir di rekaman ini.</span>'}</p>
    <h3>Buat templat pola (gaya Arbimon)</h3>
    <p class="muted">Seret kotak di sekitar <strong>satu panggilan</strong> pada spektrogram suara yang dibersihkan (0–12 kHz), beri nama jenis yang sudah Anda yakini, lalu simpan. Templat dicari ke rekaman lain di tab Pola &amp; validasi.</p>
    <div class="baris"><button class="tombol kecil" id="kanvas-mundur">‹ 60 dtk</button><span class="muted mono" id="kanvas-halaman"></span><button class="tombol kecil" id="kanvas-maju">60 dtk ›</button></div>
    <div class="wadah-kanvas" id="wadah-kanvas"><img id="kanvas" draggable="false" alt="Spektrogram untuk memilih templat"><span class="sumbu-f" style="top:2px">12 kHz</span><span class="sumbu-f" style="top:50%">6 kHz</span><span class="sumbu-f" style="bottom:2px">0</span><div class="kotak-pilih" id="kotak-pilih" hidden></div></div>
    <div class="isian">
      <label>Mulai (dtk)<input type="number" step="0.01" min="0" id="tp-mulai"></label>
      <label>Akhir (dtk)<input type="number" step="0.01" min="0" id="tp-akhir"></label>
      <label>Frek. bawah (Hz)<input type="number" step="10" min="0" max="12000" id="tp-fmin"></label>
      <label>Frek. atas (Hz)<input type="number" step="10" min="0" max="12000" id="tp-fmaks"></label>
      <label>Nama jenis<input id="tp-spesies" list="daftar-spesies-templat" placeholder="mis. Litoria infrafrenata"></label>
      <button class="tombol kecil" id="tp-putar" type="button">▶ Dengar</button>
      <button class="tombol utama" id="tp-simpan" type="button">Simpan templat</button>
    </div>
    <datalist id="daftar-spesies-templat"></datalist>
    <p id="tp-status" class="muted" role="status"></p>
    <h3>Verifikasi per pita</h3>
    <div class="gulir">${tabelLevel(d)}</div>
    <p class="muted">${puncak.length} nada gangguan di-notch: ${puncak.map((p) => `${fmt(p.frekuensi_hz, 0)} Hz`).join(", ") || "–"} · gain normalisasi ${fmt(d.penyaringan.gain_normalisasi_db)} dB</p>
    <h3>Jendela 5 detik</h3>
    <div id="status-model-detail">${statusModel(d.model)}</div>
    ${d.catatan_perch ? '<p class="status-warn">Tebakan Perch belum tersedia. Anda tetap bisa mendengarkan dan mengunduh rekaman. Coba lagi nanti untuk memberi label dan melatih model.</p>' : ""}
    ${adaMulai ? `<p class="peringatan" id="peringatan-prediksi">${peringatanModel()}</p>
    <p class="muted">Perch hanya memberi tebakan pembanding, bukan kepastian jenis katak Papua; skor relatif terhadap kumpulan kelas masing-masing kolom, bukan probabilitas keberadaan. ${d.model_kustom_aktif ? "Model Anda belajar dari label yang Anda berikan." : "Beri label sedikitnya dua kelompok berbeda, lalu pilih Latih model di tab Model &amp; label."}</p>
    <div class="gulir wadah-jendela"><table class="tabel" id="tabel-jendela"><thead><tr>
      <th>Waktu</th><th>Aktivitas suara ${pita}</th><th>Tebakan model Anda (belum diverifikasi)</th><th>Tebakan Perch: amfibi saja (belum diverifikasi)</th><th>Tebakan Perch: semua kelas (belum diverifikasi)</th><th>Label Anda</th></tr></thead><tbody>
      ${d.jendela
        .map(
          (j) => `<tr data-idx="${j.idx}">
        <td data-judul="Waktu" class="mono"><button class="tombol kecil putar" aria-label="Putar detik ${j.mulai_s} sampai ${j.akhir_s}" data-a="${j.mulai_s}" data-b="${j.akhir_s}">▶</button> ${fmt(j.mulai_s, 0)}–${fmt(j.akhir_s, 0)} detik</td>
        <td data-judul="Aktivitas suara ${pita}"><span class="bar"><i style="width:${Math.min(100, j.persen_aktif_pita_katak)}%"></i></span> <span class="mono">${fmt(j.persen_aktif_pita_katak, 0)}%</span></td>
        <td data-judul="Tebakan model Anda (belum diverifikasi)">${j.data_latih ? '<strong class="status-warn">Contoh untuk melatih model, bukan hasil pemeriksaan terpisah.</strong>' : ""}${saran(j.model_kustom)}</td>
        <td data-judul="Tebakan Perch: amfibi saja (belum diverifikasi)">${saran(j.perch_amfibi)}</td>
        <td data-judul="Tebakan Perch: semua kelas (belum diverifikasi)">${saran(j.perch_umum)}</td>
        <td data-judul="Label Anda"><label for="label-${j.idx}">Label Anda</label><input id="label-${j.idx}" aria-describedby="simpan-${j.idx}" class="label ${j.label ? "tersimpan" : ""}" list="daftar-label" value="${esc(j.label || "")}" placeholder="nama jenis"><span id="simpan-${j.idx}" class="status-label" role="status">${j.label ? "Tersimpan" : "Isi nama jenis atau bukan katak, lalu keluar dari kotak untuk menyimpan."}</span></td>
      </tr>`
        )
        .join("")}
    </tbody></table></div>
    <datalist id="daftar-label">${[...new Set([...semuaLabel, "bukan katak"])].map((l) => `<option value="${esc(l)}">`).join("")}</datalist>` : ""}
  `;
  $("#tombol-hapus").onclick = async () => {
    if (!confirm("Hapus rekaman ini beserta labelnya?")) return;
    await api(`/api/rekaman/${id}`, { method: "DELETE" });
    aktifId = null;
    $("#detail").innerHTML = '<p class="muted">Rekaman dihapus.</p>';
    $("#progres").textContent = "";
    muatDaftar();
  };
  pasangPemutar();
  pasangKanvas(id, d.durasi_s);
  document.querySelectorAll("#tabel-jendela input.label").forEach((inp) => {
    const simpan = async () => {
      const idx = Number(inp.closest("tr").dataset.idx);
      const status = $(`#simpan-${idx}`);
      status.textContent = "Menyimpan…";
      inp.disabled = true;
      try {
        const r = await api(`/api/rekaman/${id}/label`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ idx, label: inp.value }),
        });
        semuaLabel = Object.keys(r.label);
        jumlahLabel = r.label;
        inp.classList.toggle("tersimpan", !!inp.value.trim());
        status.textContent = inp.value.trim() ? "Tersimpan" : "Label dihapus.";
        status.classList.remove("status-warn");
        const st = await muatStatus();
        const el = $("#status-model-detail");
        if (el) el.innerHTML = statusModel(st.model);
        $("#peringatan-prediksi").textContent = peringatanModel();
        $("#progres").textContent = "";
        muatDaftar();
      } catch (_) {
        inp.classList.remove("tersimpan");
        status.classList.add("status-warn");
        status.innerHTML = 'Belum tersimpan. Periksa sambungan Anda. <button class="tombol ulang-simpan" type="button">Coba simpan lagi</button>';
        $("button", status).onclick = simpan;
      } finally {
        inp.disabled = false;
      }
    };
    inp.addEventListener("change", simpan);
  });
}

function pasangPemutar() {
  const audio = $("#audio-asli");
  if (!audio) return;
  let akhir = null;
  audio.addEventListener("timeupdate", () => {
    if (akhir != null && audio.currentTime >= akhir) { audio.pause(); akhir = null; }
  });
  document.querySelectorAll(".putar").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#tabel-jendela tr").forEach((tr) => tr.classList.remove("diputar"));
      b.closest("tr").classList.add("diputar");
      audio.currentTime = Number(b.dataset.a);
      akhir = Number(b.dataset.b);
      audio.play();
    })
  );
}

function unggahFile(fd, progres) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let interval;
    xhr.open("POST", "/api/analisis");
    xhr.timeout = 15 * 60 * 1000;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) progres(`Mengunggah ${Math.round(100 * e.loaded / e.total)}%`);
    };
    xhr.upload.onload = () => {
      const mulai = Date.now();
      const tampilkan = () => progres(`Menganalisis … ${Math.floor((Date.now() - mulai) / 1000)} detik berlalu`);
      tampilkan();
      interval = setInterval(tampilkan, 1000);
    };
    xhr.onload = () => {
      let data;
      try { data = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status < 200 || xhr.status >= 300) reject(new Error(pesanError(xhr.status, data?.detail)));
      else if (!data) reject(new Error("Balasan server tidak bisa dibaca. Coba lagi nanti."));
      else resolve(data);
    };
    xhr.onerror = () => reject(new Error("Tidak dapat terhubung ke server. Periksa koneksi internet lalu coba lagi."));
    xhr.ontimeout = () => reject(new Error("Analisis melebihi batas waktu 15 menit. Coba rekaman yang lebih pendek."));
    xhr.onabort = () => reject(new Error("Unggahan dibatalkan. Pilih file untuk mencoba lagi."));
    xhr.onloadend = () => clearInterval(interval);
    xhr.send(fd);
  });
}

async function unggah(files, folder = false) {
  const terfilter = $("#perch-terfilter").checked;
  const situsIsian = $("#situs-manual").value.trim().toUpperCase();
  const situs = POLA_SITUS.test(situsIsian) ? situsIsian : "";
  if (situsIsian && !situs) {
    $("#progres").textContent = "Kode situs harus berbentuk PAR diikuti 3 angka, misalnya PAR001.";
    $("#input-file").value = "";
    $("#situs-manual").focus();
    return;
  }
  const audio = [...files].filter((f) => !folder || /\.(wav|flac|mp3|m4a|ogg|aac|mpga)$/i.test(f.name));
  const dilewati = files.length - audio.length;
  let terakhir = null;
  const gagal = [];
  const progres = (pesan) => { $("#progres").textContent = [...gagal, pesan].join("\n"); };
  $("#progres").style.whiteSpace = "pre-line";
  for (const [i, f] of audio.entries()) {
    const tampilkan = (tahap) => progres(`${tahap} — ${i + 1}/${audio.length}: ${f.name}${f.size > 50 * 1024 * 1024 ? ". File besar; proses dapat memakan waktu beberapa menit." : ""}`);
    tampilkan("Mengunggah 0%");
    const fd = new FormData();
    fd.append("file", f);
    fd.append("perch_terfilter", terfilter);
    fd.append("mode_rendah", $("#mode-rendah").checked);
    if (f.webkitRelativePath) fd.append("path_relatif", f.webkitRelativePath);
    else if (situs) fd.append("path_relatif", `${situs}/${f.name}`);
    try {
      terakhir = await unggahFile(fd, tampilkan);
    } catch (e) {
      gagal.push(`${f.name} — Gagal: ${e.message}`);
    }
  }
  progres(`Selesai: ${audio.length - gagal.length} file berhasil; ${gagal.length} dari ${audio.length} file gagal.${dilewati ? ` ${dilewati} file dilewati: bukan audio.` : ""}`);
  $("#input-file").value = "";
  $("#input-folder").value = "";
  if (terakhir) buka(terakhir.id);
}

const POLA_SITUS = /^PAR\d{3}(?:_PAR\d{3})*$/;
if (navigator.userAgentData?.mobile ?? /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)) {
  $("#pemilih-folder").hidden = true;
  $("#isian-situs").hidden = false;
}
$("#input-file").addEventListener("change", (e) => e.target.files.length && unggah(e.target.files));
$("#input-folder").addEventListener("change", (e) => e.target.files.length && unggah(e.target.files, true));
const zona = $("#zona-unggah");
["dragenter", "dragover"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add("seret"); }));
["dragleave", "drop"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove("seret"); }));
zona.addEventListener("drop", (e) => e.dataTransfer.files.length && unggah(e.dataTransfer.files));

$("#tombol-contoh").addEventListener("click", async (e) => {
  const tombol = e.currentTarget;
  tombol.disabled = true;
  $("#progres").textContent = "Membuat dan menganalisis rekaman contoh … (pertama kali bisa ±30 detik untuk memuat Perch)";
  try {
    const d = await api("/api/contoh", { method: "POST" });
    $("#progres").textContent = "Contoh siap.";
    buka(d.id);
  } catch (err) {
    $("#progres").textContent = "Contoh belum bisa dibuka. Coba lagi nanti atau unggah file WAV Anda sendiri.";
  } finally {
    tombol.disabled = false;
  }
});

async function muatModel() {
  const s = await muatStatus();
  $("#hasil-latih").innerHTML = statusModel(s.model);
  if (!$("#unduh-prediksi")) {
    const a = document.createElement("a");
    a.id = "unduh-prediksi";
    a.className = "tombol";
    a.href = "/api/prediksi.csv";
    a.textContent = "Unduh prediksi (CSV)";
    $("#tombol-latih").parentElement.appendChild(a);
  }
  const tb = $("#tabel-label tbody");
  const ent = Object.entries(s.label);
  $("#peringatan-model").textContent = peringatanModel();
  tb.innerHTML = ent.length
    ? ent.map(([k, n]) => `<tr><td>${esc(k)}</td><td class="angka">${n}</td></tr>`).join("")
    : '<tr><td class="muted">Belum ada label.</td></tr>';
}

$("#tombol-latih").addEventListener("click", async (e) => {
  e.target.disabled = true;
  $("#hasil-latih").innerHTML = '<p class="muted">Melatih …</p>';
  try {
    const r = await api("/api/latih", { method: "POST" });
    $("#progres").textContent = "";
    await muatModel();
    if (!r.siap) $("#hasil-latih").insertAdjacentHTML("beforeend", '<p class="status-warn">Beri label sedikitnya dua kelompok berbeda, misalnya satu jenis katak dan bukan katak, lalu coba lagi.</p>');
    if (aktifId) buka(aktifId);
  } catch (err) {
    $("#hasil-latih").innerHTML = `<p class="status-warn">${esc(err.message)}</p>`;
  } finally {
    e.target.disabled = false;
  }
});

// --- Gaya Arbimon: templat → pencocokan → validasi → ringkasan ---------------------------------
const HALAMAN_S = 60, F_ATAS = 12000;
const json = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function putarPotongan(audio, a, b) {
  if (audio._henti) audio.removeEventListener("timeupdate", audio._henti);
  audio.currentTime = a;
  const henti = () => { if (audio.currentTime >= b) { audio.pause(); audio.removeEventListener("timeupdate", henti); audio._henti = null; } };
  audio._henti = henti;
  audio.addEventListener("timeupdate", henti);
  return audio.play();
}

const statusCari = {};

function pasangKanvas(id, durasi) {
  const img = $("#kanvas"), wadah = $("#wadah-kanvas"), kotak = $("#kotak-pilih");
  if (!img) return;
  let mulai = 0, awal = null;
  const panjang = () => Math.min(HALAMAN_S, durasi - mulai);
  const isi = { a: $("#tp-mulai"), b: $("#tp-akhir"), f0: $("#tp-fmin"), f1: $("#tp-fmaks") };
  api("/api/spesies").then((l) => ($("#daftar-spesies-templat").innerHTML = l.map((x) => `<option value="${esc(x)}">`).join(""))).catch(() => {});
  const tampil = () => {
    img.src = `/api/rekaman/${id}/kanvas.png?mulai=${mulai}`;
    $("#kanvas-halaman").textContent = `${fmt(mulai, 0)}–${fmt(mulai + panjang(), 0)} dtk dari ${fmt(durasi, 0)}`;
    $("#kanvas-mundur").disabled = mulai <= 0;
    $("#kanvas-maju").disabled = mulai + HALAMAN_S >= durasi;
    gambarKotak();
  };
  const gambarKotak = () => {
    const a = +isi.a.value, b = +isi.b.value, f0 = +isi.f0.value, f1 = +isi.f1.value;
    if (!(b > a && f1 > f0) || b < mulai || a > mulai + panjang()) { kotak.hidden = true; return; }
    const w = img.clientWidth, h = img.clientHeight, sx = w / panjang();
    kotak.hidden = false;
    kotak.style.left = `${Math.max(0, (a - mulai) * sx)}px`;
    kotak.style.width = `${(Math.min(b, mulai + panjang()) - Math.max(a, mulai)) * sx}px`;
    kotak.style.top = `${(1 - Math.min(f1, F_ATAS) / F_ATAS) * h}px`;
    kotak.style.height = `${(Math.min(f1, F_ATAS) - f0) / F_ATAS * h}px`;
  };
  const titik = (e) => {
    const r = img.getBoundingClientRect();
    const fx = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const fy = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
    return { t: mulai + fx * panjang(), f: (1 - fy) * F_ATAS };
  };
  const set = (p, q) => {
    isi.a.value = Math.min(p.t, q.t).toFixed(2);
    isi.b.value = Math.max(p.t, q.t).toFixed(2);
    isi.f0.value = Math.round(Math.min(p.f, q.f) / 10) * 10;
    isi.f1.value = Math.round(Math.max(p.f, q.f) / 10) * 10;
    gambarKotak();
  };
  wadah.addEventListener("pointerdown", (e) => { awal = titik(e); wadah.setPointerCapture(e.pointerId); });
  wadah.addEventListener("pointermove", (e) => awal && set(awal, titik(e)));
  wadah.addEventListener("pointerup", (e) => { if (awal) set(awal, titik(e)); awal = null; });
  Object.values(isi).forEach((el) => el.addEventListener("input", gambarKotak));
  img.addEventListener("load", gambarKotak);
  $("#kanvas-mundur").onclick = () => { mulai = Math.max(0, mulai - HALAMAN_S); tampil(); };
  $("#kanvas-maju").onclick = () => { mulai += HALAMAN_S; tampil(); };
  $("#tp-putar").onclick = () => {
    if (+isi.b.value > +isi.a.value) putarPotongan($("#audio-terfilter"), +isi.a.value, +isi.b.value);
  };
  $("#tp-simpan").onclick = async (e) => {
    const st = $("#tp-status");
    e.target.disabled = true;
    try {
      const t = await api("/api/templat", json({
        rekaman_id: id, mulai_s: +isi.a.value, akhir_s: +isi.b.value,
        f_min: +isi.f0.value, f_maks: +isi.f1.value, spesies: $("#tp-spesies").value,
      }));
      st.className = "status-ok";
      st.textContent = `Templat “${t.spesies}” tersimpan. Buka tab Pola & validasi untuk mencarinya di rekaman lain.`;
    } catch (err) {
      st.className = "status-warn";
      st.textContent = err.message;
    } finally {
      e.target.disabled = false;
    }
  };
  tampil();
}

let templatAktif = null;

async function muatPola() {
  const [templat, spesies] = await Promise.all([api("/api/templat"), api("/api/spesies")]);
  $("#daftar-templat").innerHTML = templat.length
    ? templat.map((t) => `<div class="item-templat ${t.id === templatAktif ? "aktif" : ""}" data-id="${t.id}">
        <img src="/api/templat/${t.id}/gambar.png" alt="Templat ${esc(t.spesies)}">
        <div><strong>${esc(t.spesies)}</strong></div>
        <div class="muted">${esc(t.nama_file)} · ${fmt(t.mulai_s, 2)}–${fmt(t.akhir_s, 2)} dtk · ${fmt(t.f_min, 0)}–${fmt(t.f_maks, 0)} Hz</div>
        <div class="muted">${t.rekaman_dicari} rekaman dicari · ${t.cocok} kandidat: <span class="status-ok">${t.hadir} hadir</span>, ${t.tidak} tidak, <span class="status-warn">${t.belum} belum divalidasi</span></div>
        <button class="tombol kecil buka-templat">Buka</button></div>`).join("")
    : '<p class="muted">Belum ada templat. Buat dari spektrogram di tab Analisis.</p>';
  document.querySelectorAll(".buka-templat").forEach((b) => (b.onclick = () => bukaTemplat(b.closest(".item-templat").dataset.id)));
  const pilih = $("#pilih-spesies"), lama = pilih.value;
  pilih.innerHTML = spesies.map((x) => `<option>${esc(x)}</option>`).join("");
  if (spesies.includes(lama)) pilih.value = lama;
  muatRingkasan();
  if (templatAktif && templat.some((t) => t.id === templatAktif)) bukaTemplat(templatAktif, false);
}

async function bukaTemplat(tid, gulir = true) {
  templatAktif = tid;
  document.querySelectorAll(".item-templat").forEach((el) => el.classList.toggle("aktif", el.dataset.id === tid));
  const panel = $("#panel-templat");
  const situs = await api("/api/situs");
  const t = (await api("/api/templat")).find((x) => x.id === tid);
  if (!t) { panel.hidden = true; return; }
  panel.hidden = false;
  panel.innerHTML = `<h2>Templat: ${esc(t.spesies)}</h2>
    <div class="isian">
      <label>Cari di<select id="cari-situs"><option value="">Semua rekaman</option>${situs.filter((s) => s.situs).map((s) => `<option value="${esc(s.situs)}">${esc(s.situs)} (${s.rekaman})</option>`).join("")}</select></label>
      <label>Skor minimum<input type="number" id="cari-ambang" min="0.1" max="0.99" step="0.05" value="0.5"></label>
      <label>Maks. kandidat per rekaman<input type="number" id="cari-maks" min="1" max="500" value="20"></label>
      <button class="tombol utama" id="tombol-cari">Cari pola</button>
      <button class="tombol" id="hapus-templat">Hapus templat</button>
    </div>
    <p class="muted">Mencari ulang mengganti kandidat yang belum divalidasi; kandidat yang sudah Anda tandai tetap disimpan.</p>
    <p id="status-cari" class="muted" role="status">${esc(statusCari[tid] || "")}</p>
    <div class="baris">
      <label for="filter-cocok">Tampilkan</label>
      <select id="filter-cocok"><option value="belum">Belum divalidasi</option><option value="hadir">Hadir</option><option value="tidak">Tidak</option><option value="semua">Semua</option></select>
      <button class="tombol kecil" id="semua-tidak">Tandai semua yang tampil: Tidak</button>
    </div>
    <audio id="audio-cocok" preload="none"></audio>
    <div id="daftar-cocok" class="grid-cocok"></div>`;
  $("#tombol-cari").onclick = async (e) => {
    e.target.disabled = true;
    $("#status-cari").textContent = "Mencari … (rekaman panjang bisa memakan beberapa menit)";
    try {
      const r = await api(`/api/templat/${tid}/jalankan`, json({
        situs: $("#cari-situs").value || null, ambang: +$("#cari-ambang").value, maks_per_rekaman: +$("#cari-maks").value,
      }));
      statusCari[tid] = `${r.rekaman_dicari} rekaman dicari, ${r.kandidat_baru} kandidat baru${r.gagal ? `, ${r.gagal} rekaman gagal dibaca` : ""}. Semua kandidat belum divalidasi.`;
      $("#status-cari").textContent = statusCari[tid];
      await muatPola();
    } catch (err) {
      $("#status-cari").textContent = err.message;
    } finally {
      e.target.disabled = false;
    }
  };
  $("#hapus-templat").onclick = async () => {
    if (!confirm("Hapus templat ini beserta semua kandidat dan validasinya?")) return;
    await api(`/api/templat/${tid}`, { method: "DELETE" });
    templatAktif = null;
    panel.hidden = true;
    muatPola();
  };
  $("#filter-cocok").onchange = () => muatCocok(tid);
  $("#semua-tidak").onclick = async () => {
    const ids = [...document.querySelectorAll(".item-cocok")].map((el) => +el.dataset.id);
    if (!ids.length || !confirm(`Tandai ${ids.length} kandidat yang tampil sebagai Tidak?`)) return;
    await api("/api/cocok/validasi", json({ ids, validasi: "tidak" }));
    muatPola();
  };
  await muatCocok(tid);
  if (gulir) panel.scrollIntoView({ behavior: "smooth" });
}

const labelValidasi = (v) => (v === "hadir" ? '<span class="lencana hadir">Hadir (divalidasi)</span>'
  : v === "tidak" ? '<span class="lencana">Tidak (divalidasi)</span>' : '<span class="lencana belum">Belum divalidasi</span>');

async function muatCocok(tid) {
  const rows = await api(`/api/templat/${tid}/cocok?status=${$("#filter-cocok").value}`);
  const wadah = $("#daftar-cocok");
  wadah.innerHTML = rows.length ? rows.slice(0, 200).map((c) => `<div class="item-cocok ${c.validasi || ""}" data-id="${c.id}">
      <img loading="lazy" src="/api/cocok/${c.id}/gambar.png" alt="Kandidat">
      <div>${labelValidasi(c.validasi)} <span class="muted mono">skor ${fmt(c.skor, 2)}</span></div>
      <div class="muted" style="word-break:break-all">${esc(c.situs || "tanpa situs")} · ${esc(c.nama_file)} · ${fmt(c.mulai_s, 1)} dtk</div>
      <div class="baris">
        <button class="tombol kecil putar-cocok" data-aksi="putar" data-rid="${c.rekaman_id}" data-a="${c.mulai_s}" data-b="${c.akhir_s}" aria-pressed="false">▶ Putar</button>
        <button class="tombol kecil" data-aksi="hadir">Hadir</button>
        <button class="tombol kecil" data-aksi="tidak">Tidak</button>
        ${c.validasi ? '<button class="tombol kecil" data-aksi="">Batalkan</button>' : ""}
      </div></div>`).join("") + (rows.length > 200 ? `<p class="muted">Menampilkan 200 dari ${rows.length} kandidat (skor tertinggi).</p>` : "")
    : '<p class="muted">Tidak ada kandidat untuk filter ini.</p>';
  wadah.querySelectorAll("button").forEach((b) => (b.onclick = async () => {
    const item = b.closest(".item-cocok");
    if (b.dataset.aksi === "putar") {
      const audio = $("#audio-cocok"), src = `/api/rekaman/${b.dataset.rid}/audio/terfilter`;
      const aktif = b.getAttribute("aria-pressed") === "true";
      const tampil = (el, teks, ditekan) => { el.textContent = teks; el.setAttribute("aria-pressed", ditekan); };
      wadah.querySelectorAll(".putar-cocok").forEach((el) => tampil(el, "▶ Putar", false));
      audio.pause();
      if (aktif) return;
      tampil(b, "Memuat …", true);
      audio.onplaying = () => tampil(b, "■ Hentikan", true);
      audio.onpause = () => audio.paused && tampil(b, "▶ Putar", false);
      if (!audio.src.endsWith(src)) audio.src = src;
      // play() memulai pemuatan meski preload="none"; currentTime menyimpan posisi awal.
      putarPotongan(audio, Math.max(0, +b.dataset.a - 0.3), +b.dataset.b + 0.3)
        .catch(() => tampil(b, "▶ Putar", false));
      return;
    }
    await api("/api/cocok/validasi", json({ ids: [+item.dataset.id], validasi: b.dataset.aksi || null }));
    muatPola();
  }));
}

async function muatRingkasan() {
  const sp = $("#pilih-spesies").value, el = $("#ringkasan-hadir");
  $("#unduh-matriks").href = sp ? `/api/matriks.csv?spesies=${encodeURIComponent(sp)}` : "#";
  if (!sp) { el.innerHTML = '<p class="muted">Belum ada templat.</p>'; return; }
  const r = await api(`/api/ringkasan?spesies=${encodeURIComponent(sp)}`);
  if (!r.rekaman_dicari) { el.innerHTML = '<p class="muted">Templat jenis ini belum dicari di rekaman mana pun.</p>'; return; }
  const kolomTgl = [...new Set(Object.values(r.tanggal).flatMap((v) => Object.keys(v)))].sort();
  const kolomJam = [...new Set(Object.values(r.jam).flatMap((v) => Object.keys(v)))].sort();
  const kode = { hadir: "1", tidak: "0", belum: "?" };
  el.innerHTML = `<p>${r.rekaman_hadir} dari ${r.rekaman_dicari} rekaman hadir (divalidasi manual) · ${r.situs_hadir} dari ${r.situs_dicari} situs · okupansi naif ${r.okupansi_naif == null ? "–" : fmt(r.okupansi_naif * 100, 0) + "%"}</p>
    ${r.rekaman_belum_divalidasi ? `<p class="peringatan">${r.rekaman_belum_divalidasi} rekaman masih punya kandidat yang belum divalidasi (?). Angka di atas hanya menghitung yang sudah Anda tandai Hadir.</p>` : ""}
    <h3>Situs × tanggal</h3>
    <div class="gulir"><table class="tabel matriks"><thead><tr><th>Situs</th>${kolomTgl.map((t) => `<th>${esc(t)}</th>`).join("")}</tr></thead><tbody>
    ${Object.entries(r.tanggal).sort().map(([s, v]) => `<tr><td>${esc(s)}</td>${kolomTgl.map((t) => (v[t] ? `<td class="${v[t]}">${kode[v[t]]}</td>` : '<td class="muted">NA</td>')).join("")}</tr>`).join("")}
    </tbody></table></div>
    <h3>Situs × jam mulai rekaman (WIT)</h3>
    <div class="gulir"><table class="tabel matriks"><thead><tr><th>Situs</th>${kolomJam.map((j) => `<th>${j === "?" ? "jam ?" : esc(j) + ":00"}</th>`).join("")}</tr></thead><tbody>
    ${Object.entries(r.jam).sort().map(([s, v]) => `<tr><td>${esc(s)}</td>${kolomJam.map((j) => {
      const c = v[j];
      if (!c) return '<td class="muted">NA</td>';
      return `<td class="${c.hadir ? "hadir" : c.belum ? "belum" : "tidak"}">${c.hadir}/${c.rekaman}${c.belum ? ` (+${c.belum}?)` : ""}</td>`;
    }).join("")}</tr>`).join("")}
    </tbody></table></div>
    <p class="muted">Sel jam: rekaman hadir / rekaman dicari; (+n?) = rekaman dengan kandidat belum divalidasi. Rekaman harian tanpa jam mulai masuk kolom “jam ?”.</p>`;
}
$("#pilih-spesies").addEventListener("change", muatRingkasan);

async function muatSitusSoundscape() {
  const pilih = $("#pilih-situs-ss"), lama = pilih.value;
  const situs = await api("/api/situs");
  pilih.innerHTML = '<option value="">Semua situs</option>' + situs.filter((s) => s.situs).map((s) => `<option value="${esc(s.situs)}">${esc(s.situs)} (${s.rekaman})</option>`).join("");
  pilih.value = lama;
}

$("#tombol-soundscape").addEventListener("click", async (e) => {
  const situs = $("#pilih-situs-ss").value, q = situs ? `?situs=${encodeURIComponent(situs)}` : "";
  const info = $("#info-soundscape"), img = $("#gambar-soundscape");
  e.target.disabled = true;
  info.textContent = "Menghitung soundscape … (pertama kali bisa lama untuk rekaman panjang)";
  try {
    const h = await api(`/api/soundscape${q}`);
    img.src = `/api/soundscape.png${q}${q ? "&" : "?"}t=${Date.now()}`;
    $("#buka-soundscape").href = img.src;
    img.hidden = false;
    $("#buka-soundscape").hidden = false;
    info.textContent = `${h.rekaman} rekaman · sumbu waktu: ${h.sumbu}${h.rekaman_tanpa_jam_dilewati ? ` · ${h.rekaman_tanpa_jam_dilewati} rekaman tanpa jam mulai tidak dimasukkan` : ""}.`;
  } catch (err) {
    img.hidden = true;
    $("#buka-soundscape").hidden = true;
    info.textContent = err.message;
  } finally {
    e.target.disabled = false;
  }
});

muatStatus().then(muatDaftar);
