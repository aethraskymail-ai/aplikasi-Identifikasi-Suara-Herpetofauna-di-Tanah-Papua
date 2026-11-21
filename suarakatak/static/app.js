const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 1) => (n == null ? "–" : Number(n).toLocaleString("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d }));
// Dibulatkan ke bawah agar skor beberapa kelas tidak berjumlah lebih dari 100%.
const persenSkor = (s) => (s > 0 && s < 0.01 ? "<1%" : `${Math.floor(s * 100 + 1e-9)}%`);
let aktifId = null;
let semuaLabel = [];

async function api(url, opt) {
  const r = await fetch(url, { credentials: "same-origin", ...opt });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
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
  return s;
}

async function muatDaftar() {
  const rows = await api("/api/rekaman");
  const ul = $("#daftar");
  ul.innerHTML = rows.length ? "" : '<li class="muted">Belum ada rekaman.</li>';
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
  return `<div class="saran">${list.map((p) => `<div>${esc(p.label)} <span class="muted mono">${persenSkor(p.skor)}</span></div>`).join("")}</div>`;
}

function statusModel(r) {
  if (!r.siap) return '<p class="status-warn">Belum ada model terlatih. Beri label ≥2 kelas, lalu klik Latih model.</p>';
  return `<p class="${r.usang ? "status-warn" : "muted"}">${r.usang ? "Label berubah sejak model dilatih — latih ulang. " : ""}Model dilatih: ${esc(r.dilatih_pada)} · ${r.n} label, ${Object.keys(r.kelas).length} kelas.</p>
    <p class="status-warn">Tebakan belum terverifikasi; skor model tidak terkalibrasi, bukan kepastian jenis.${r.data_kecil ? " Data latih sedikit: jangan gunakan sebagai identifikasi terverifikasi." : ""}</p>
    <p class="muted">CV antarrekaman: ${r.akurasi_cv == null ? "belum tersedia" : fmt(r.akurasi_cv * 100, 0) + "% (" + r.lipatan_cv + " lipatan)"}. ${esc(r.pesan || "")}</p>`;
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
  $("#detail").innerHTML = `
    <div class="baris" style="justify-content:space-between">
      <h2 style="margin:0;word-break:break-all">${esc(d.nama_file)}</h2>
      <button class="tombol kecil" id="tombol-hapus">Hapus</button>
    </div>
    <div class="info">
      <span><b>Durasi</b> ${fmt(d.durasi_s)} dtk</span>
      <span><b>Sample rate</b> ${d.sample_rate_asli} Hz</span>
      <span><b>Mode</b> ${d.mode_rendah ? "Frekuensi rendah · highpass 400 Hz · bukan metode tervalidasi" : "Standar · highpass 2100 Hz"}</span>
      ${am.waktu ? `<span><b>Waktu</b> ${esc(am.waktu)} WIT</span>` : ""}
      ${am.par ? `<span><b>Lokasi</b> ${esc(am.par)}</span>` : ""}
      <span>${jendela}</span>
      <span><b>Aktivitas pita ${pita}</b> ${fmt(d.aktivitas.detik_aktif)} dtk (${fmt(d.aktivitas.persen_aktif)}%), ${d.aktivitas.jumlah_segmen} segmen</span>
    </div>
    <div class="dua">
      <div><div class="muted">Asli</div><audio id="audio-asli" controls preload="metadata" src="/api/rekaman/${id}/audio/asli"></audio>
        <img class="spek" src="/api/rekaman/${id}/spektrogram/sebelum.png" alt="Spektrogram sebelum"></div>
      <div><div class="muted">Terfilter (unduh: klik kanan pemutar)</div><audio id="audio-terfilter" controls preload="metadata" src="/api/rekaman/${id}/audio/terfilter"></audio>
        <img class="spek" src="/api/rekaman/${id}/spektrogram/sesudah.png" alt="Spektrogram sesudah"></div>
    </div>
    <h3>Verifikasi per pita</h3>
    <div class="gulir">${tabelLevel(d)}</div>
    <p class="muted">${puncak.length} nada gangguan di-notch: ${puncak.map((p) => `${fmt(p.frekuensi_hz, 0)} Hz`).join(", ") || "–"} · gain normalisasi ${fmt(d.penyaringan.gain_normalisasi_db)} dB</p>
    <h3>Jendela 5 detik</h3>
    <div id="status-model-detail">${statusModel(d.model)}</div>
    ${d.catatan_perch ? `<p class="status-warn">${esc(d.catatan_perch)}</p>` : ""}
    ${adaMulai ? `<p class="status-warn">Saran model — belum diverifikasi; skor relatif, bukan probabilitas keberadaan.</p>
    <p class="muted">Perch = saran model global, hanya pembanding, belum terverifikasi; skor dihitung relatif terhadap kumpulan kelas masing-masing kolom. Model kustom = tebakan dari model terakhir yang Anda latih; skor tidak terkalibrasi. Data latih bukan evaluasi independen.</p>
    <div class="gulir"><table class="tabel" id="tabel-jendela"><thead><tr>
      <th>Waktu</th><th>Aktivitas ${pita}</th><th>Model kustom</th><th>Perch: kelas amfibi saja</th><th>Perch: semua kelas</th><th>Label Anda</th></tr></thead><tbody>
      ${d.jendela
        .map(
          (j) => `<tr data-idx="${j.idx}">
        <td class="mono"><button class="tombol kecil putar" data-a="${j.mulai_s}" data-b="${j.akhir_s}">▶</button> ${fmt(j.mulai_s, 0)}–${fmt(j.akhir_s, 0)} s</td>
        <td><span class="bar"><i style="width:${Math.min(100, j.persen_aktif_pita_katak)}%"></i></span> <span class="mono">${fmt(j.persen_aktif_pita_katak, 0)}%</span></td>
        <td>${j.data_latih ? '<strong class="status-warn">Data latih — bukan identifikasi independen</strong>' : ""}${saran(j.model_kustom)}</td>
        <td>${saran(j.perch_amfibi)}</td>
        <td>${saran(j.perch_umum)}</td>
        <td><input class="label ${j.label ? "tersimpan" : ""}" list="daftar-label" value="${esc(j.label || "")}" placeholder="nama jenis / bukan katak"></td>
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
    muatDaftar();
  };
  pasangPemutar();
  document.querySelectorAll("#tabel-jendela input.label").forEach((inp) => {
    const simpan = async () => {
      const idx = Number(inp.closest("tr").dataset.idx);
      const r = await api(`/api/rekaman/${id}/label`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idx, label: inp.value }),
      });
      semuaLabel = Object.keys(r.label);
      inp.classList.toggle("tersimpan", !!inp.value.trim());
      const st = await api("/api/status");
      const el = $("#status-model-detail");
      if (el) el.innerHTML = statusModel(st.model);
      muatDaftar();
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
    fd.append("mode_rendah", $("#mode-rendah").checked);
    try {
      terakhir = await api("/api/analisis", { method: "POST", body: fd });
    } catch (e) {
      $("#progres").textContent = `Gagal: ${e.message}`;
      return;
    }
  }
  $("#progres").textContent = `Selesai: ${files.length} file.`;
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
    $("#progres").textContent = `Gagal: ${err.message}`;
  } finally {
    e.target.disabled = false;
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
  tb.innerHTML = ent.length
    ? ent.map(([k, n]) => `<tr><td>${esc(k)}</td><td class="angka">${n}</td></tr>`).join("")
    : '<tr><td class="muted">Belum ada label.</td></tr>';
}

$("#tombol-latih").addEventListener("click", async (e) => {
  e.target.disabled = true;
  $("#hasil-latih").innerHTML = '<p class="muted">Melatih …</p>';
  try {
    const r = await api("/api/latih", { method: "POST" });
    await muatModel();
    if (!r.siap) $("#hasil-latih").insertAdjacentHTML("beforeend", `<p class="status-warn">${esc(r.pesan)}</p>`);
    if (aktifId) buka(aktifId);
  } catch (err) {
    $("#hasil-latih").innerHTML = `<p class="status-warn">${esc(err.message)}</p>`;
  } finally {
    e.target.disabled = false;
  }
});

muatStatus().then(muatDaftar);
