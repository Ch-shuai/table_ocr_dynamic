document.addEventListener('DOMContentLoaded', function() {
  // Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const tabId = 'tab-' + btn.dataset.tab;
      const panel = document.getElementById(tabId);
      if (panel) panel.classList.add('active');
    });
  });

  // File drop zone
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const fileName = document.getElementById('fileName');
  const confSlider = document.getElementById('confSlider');
  const confValue = document.getElementById('confValue');

  if (dropZone) {
    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
      e.preventDefault(); dropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        fileName.textContent = e.dataTransfer.files[0].name;
      }
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length) fileName.textContent = fileInput.files[0].name;
    });
  }

  if (confSlider && confValue) {
    confSlider.addEventListener('input', () => confValue.textContent = confSlider.value);
  }

  // Form submit loading state
  const form = document.querySelector('form');
  if (form) {
    form.addEventListener('submit', () => {
      const btn = form.querySelector('.submit-btn');
      if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ 解析中，请稍候...';
      }
    });
  }

  // Image grid overlay
  const img = document.getElementById('originalImage');
  const wrapper = document.getElementById('imageWrapper');
  if (img && wrapper) {
    img.addEventListener('load', () => {
      const w = img.naturalWidth, h = img.naturalHeight;
      const cols = JSON.parse(img.dataset.columns || '[]');
      const rows = JSON.parse(img.dataset.rows || '[]');
      cols.forEach(col => {
        createLine(wrapper, col.x1 / w * 100, 0, 'v');
        createLine(wrapper, col.x2 / w * 100, 0, 'v');
      });
      rows.forEach(row => {
        createLine(wrapper, 0, row.y1 / h * 100, 'h');
        createLine(wrapper, 0, row.y2 / h * 100, 'h');
      });
    });
  }

  function createLine(wrapper, x, y, type) {
    const line = document.createElement('div');
    line.className = 'grid-line ' + (type === 'v' ? 'v-line' : 'h-line');
    if (type === 'v') { line.style.left = x + '%'; line.style.top = '0'; line.style.height = '100%'; }
    else { line.style.top = y + '%'; line.style.left = '0'; line.style.width = '100%'; }
    wrapper.appendChild(line);
  }

  // Lazy load stock JSON content
  document.querySelectorAll('.stock-record').forEach(details => {
    details.addEventListener('toggle', () => {
      if (details.open) {
        const pre = details.querySelector('pre');
        if (pre && pre.textContent === '加载中...') {
          const runId = document.querySelector('.result-section')?.dataset.runId;
          const filename = details.querySelector('summary')?.textContent;
          if (runId && filename) {
            fetch(`/stock_json/${runId}/${filename}`)
              .then(r => r.json())
              .then(data => { pre.textContent = JSON.stringify(data, null, 2); })
              .catch(() => { pre.textContent = '加载失败'; });
          }
        }
      }
    });
  });
});
