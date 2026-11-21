const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 1) => (n == null ? "–" : Number(n).toLocaleString("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d }));
// Dibulatkan ke bawah agar skor beberapa kelas tidak berjumlah lebih dari 100%.
const persenSkor = (s) => (s > 0 && s < 0.01 ? "<1%" : `${Math.floor(s * 100 + 1e-9)}%`);
let aktifId = null;
let semuaLabel = [];
let jumlahLabel = {};
let modelTeruji = false;

function peringatanModel() {
  const jumlah = Object.values(jumlahLabel);
  if (jumlah.length < 2 || jumlah.some((n) => n < 10)) {
    return 'Hasil belum dapat diandalkan. Tambahkan sedikitnya 10 label yang sudah diperiksa untuk setiap kelompok. Jika hasil belum diuji dengan contoh lain, ketepatannya belum diketahui. Semua tebakan tetap perlu diperiksa ahli.';
  }
  return modelTeruji
    ? 'Semua tebakan belum diverifikasi. Persentase tinggi bukan bukti bahwa jenisnya benar; mintalah pemeriksaan ahli.'
    : 'Hasil belum dapat diandalkan karena hasil uji belum tersedia di halaman ini. Pilih Latih model untuk menguji kembali dari label Anda. Semua tebakan tetap perlu diperiksa ahli.';
}

async function api(url, opt) {
  let r;
  try {
    r = await fetch(url, { credentials: "same-origin", ...opt });
  } catch (_) {
    throw new Error('Belum berhasil. Periksa sambungan Anda lalu coba lagi.');
  }
  if (!r.ok) {
    throw new Error('Belum berhasil. Periksa sambungan Anda lalu coba lagi.');
  }
  return r.json();
}

document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("aktif", x === b));
    document.querySelectorAll("main > section").forEach((s) => (s.hidden = s.id !== "tab-" + b.dataset.tab));
    if (b.dataset.tab === "model") muatModel();
  })
);

async function muatStatus() {
  const s = await api("/api/status");
  $("#versi").textContent = s.versi;
  semuaLabel = Object.keys(s.label);
  jumlahLabel = s.label;
  return s;
}

async function muatDaftar() {
  const rows = await api("/api/rekaman");
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

function tabelLevel(d) {
  const p = d.penyaringan;
  return `<table class="tabel"><thead><tr><th>Pita</th><th class="angka">Rata² sebelum</th><th class="angka">Rata² sesudah</th><th class="angka">Perubahan</th></tr></thead><tbody>${Object.keys(p.level_sebelum)
    .map((k) => {
      const a = p.level_sebelum[k].mean_db, b = p.level_sesudah[k].mean_db;
      return `<tr><td>${esc(k)}</td><td class="angka">${fmt(a)} dB</td><td class="angka">${fmt(b)} dB</td><td class="angka">${fmt(b - a)} dB</td></tr>`;
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
  const namaAsli = d.nama_file.split(/[\\/]/).pop().replace(/ \([^)]*\)$/, "");
  const namaDibersihkan = namaAsli.replace(/\.[^.]+$/, "") + "-dibersihkan.wav";
  $("#detail").innerHTML = `
    <div class="baris" style="justify-content:space-between">
      <h2 style="margin:0;word-break:break-all">${esc(d.nama_file)}</h2>
      <button class="tombol kecil" id="tombol-hapus">Hapus</button>
    </div>
    <div class="info">
      <span><b>Durasi</b> ${fmt(d.durasi_s)} dtk</span>
      <span><b>Sample rate</b> ${d.sample_rate_asli} Hz</span>
      ${am.waktu ? `<span><b>Waktu</b> ${esc(am.waktu)} WIT</span>` : ""}
      ${am.par ? `<span><b>Lokasi</b> ${esc(am.par)}</span>` : ""}
      <span>${jendela}</span>
      <span><b>Aktivitas pita katak</b> ${fmt(d.aktivitas.detik_aktif)} dtk (${fmt(d.aktivitas.persen_aktif)}%), ${d.aktivitas.jumlah_segmen} segmen</span>
    </div>
    <div class="dua">
      <div><div class="muted">Asli</div><audio id="audio-asli" controls preload="metadata" src="/api/rekaman/${id}/audio/asli"></audio>
        <a class="tombol unduh-audio" href="/api/rekaman/${id}/audio/asli" download="${esc(namaAsli)}">Unduh rekaman asli</a>
        <img class="spek" src="/api/rekaman/${id}/spektrogram/sebelum.png" alt="Spektrogram sebelum"></div>
      <div><div class="muted">Suara yang dibersihkan</div><audio id="audio-terfilter" controls preload="metadata" src="/api/rekaman/${id}/audio/terfilter"></audio>
        <a class="tombol unduh-audio" href="/api/rekaman/${id}/audio/terfilter" download="${esc(namaDibersihkan)}">Unduh suara yang dibersihkan</a>
        <img class="spek" src="/api/rekaman/${id}/spektrogram/sesudah.png" alt="Spektrogram sesudah"></div>
    </div>
    <h3>Verifikasi per pita</h3>
    <div class="gulir">${tabelLevel(d)}</div>
    <p class="muted">${puncak.length} nada gangguan di-notch: ${puncak.map((p) => `${fmt(p.frekuensi_hz, 0)} Hz`).join(", ") || "–"} · gain normalisasi ${fmt(d.penyaringan.gain_normalisasi_db)} dB</p>
    <h3>Jendela 5 detik</h3>
    ${d.catatan_perch ? '<p class="status-warn">Tebakan Perch belum tersedia. Anda tetap bisa mendengarkan dan mengunduh rekaman. Coba lagi nanti untuk memberi label dan melatih model.</p>' : ""}
    ${adaMulai ? `<p class="peringatan" id="peringatan-prediksi">${peringatanModel()}</p>
    <p class="muted">Perch hanya memberi tebakan pembanding, bukan kepastian jenis katak Papua. ${d.model_kustom_aktif ? "Model Anda belajar dari label yang Anda berikan." : "Beri label sedikitnya dua kelompok berbeda, lalu pilih Latih model di tab Model &amp; label."}</p>
    <div class="gulir wadah-jendela"><table class="tabel" id="tabel-jendela"><thead><tr>
      <th>Waktu</th><th>Aktivitas suara</th><th>Tebakan model Anda (belum diverifikasi)</th><th>Tebakan Perch (belum diverifikasi)</th><th>Tebakan Perch lainnya (belum diverifikasi)</th><th>Label Anda</th></tr></thead><tbody>
      ${d.jendela
        .map(
          (j) => `<tr data-idx="${j.idx}">
        <td data-judul="Waktu" class="mono"><button class="tombol kecil putar" aria-label="Putar detik ${j.mulai_s} sampai ${j.akhir_s}" data-a="${j.mulai_s}" data-b="${j.akhir_s}">▶</button> ${fmt(j.mulai_s, 0)}–${fmt(j.akhir_s, 0)} detik</td>
        <td data-judul="Aktivitas suara"><span class="bar"><i style="width:${Math.min(100, j.persen_aktif_pita_katak)}%"></i></span> <span class="mono">${fmt(j.persen_aktif_pita_katak, 0)}%</span></td>
        <td data-judul="Tebakan model Anda (belum diverifikasi)">${saran(j.model_kustom)}</td>
        <td data-judul="Tebakan Perch (belum diverifikasi)">${saran(j.perch_amfibi)}</td>
        <td data-judul="Tebakan Perch lainnya (belum diverifikasi)">${saran(j.perch_umum)}</td>
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

async function unggah(files) {
  const terfilter = $("#perch-terfilter").checked;
  let terakhir = null;
  for (const [i, f] of [...files].entries()) {
    $("#progres").textContent = `Menganalisis ${i + 1}/${files.length}: ${f.name} …`;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("perch_terfilter", terfilter);
    try {
      terakhir = await api("/api/analisis", { method: "POST", body: fd });
    } catch (e) {
      $("#progres").textContent = "Rekaman belum bisa dibaca. File mungkin rusak atau jenisnya belum didukung. Coba file WAV lain dan periksa sambungan Anda.";
      $("#input-file").value = "";
      return;
    }
  }
  $("#progres").textContent = `Selesai: ${files.length} file.`;
  $("#input-file").value = "";
  if (terakhir) buka(terakhir.id);
}

$("#input-file").addEventListener("change", (e) => e.target.files.length && unggah(e.target.files));
const zona = $("#zona-unggah");
["dragenter", "dragover"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add("seret"); }));
["dragleave", "drop"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove("seret"); }));
zona.addEventListener("drop", (e) => e.dataTransfer.files.length && unggah(e.dataTransfer.files));

$("#tombol-contoh").addEventListener("click", async (e) => {
  e.target.disabled = true;
  $("#progres").textContent = "Membuat dan menganalisis rekaman contoh … (pertama kali bisa ±30 detik untuk memuat Perch)";
  try {
    const d = await api("/api/contoh", { method: "POST" });
    $("#progres").textContent = "Contoh siap.";
    buka(d.id);
  } catch (err) {
    $("#progres").textContent = "Contoh belum bisa dibuka. Coba lagi nanti atau unggah file WAV Anda sendiri.";
  } finally {
    e.target.disabled = false;
  }
});

async function muatModel() {
  const s = await muatStatus();
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
    modelTeruji = r.siap && r.akurasi_cv != null && Object.values(r.kelas).every((n) => n >= 10);
    $("#progres").textContent = "";
    $("#hasil-latih").innerHTML = r.siap
      ? `<p class="status-ok">Latihan selesai: ${r.n} label dalam ${Object.keys(r.kelas).length} kelompok. ${r.akurasi_cv == null ? "Ketepatan belum bisa diuji. Tambahkan contoh untuk setiap kelompok." : "Hasil uji dari label Anda: " + fmt(r.akurasi_cv * 100, 0) + "% cocok. Ini bukan jaminan untuk rekaman baru."}</p>`
      : '<p class="status-warn">Beri label sedikitnya dua kelompok berbeda, misalnya satu jenis katak dan bukan katak, lalu coba lagi.</p>';
    if (aktifId) buka(aktifId);
  } catch (err) {
    $("#hasil-latih").innerHTML = `<p class="status-warn">${esc(err.message)}</p>`;
  } finally {
    e.target.disabled = false;
    muatModel();
  }
});

muatStatus().then(muatDaftar);
