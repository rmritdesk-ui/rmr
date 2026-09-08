(() => {
  const slug = document.body.dataset.siteSlug;
  const submit = (form, status, url, success) => {
    if (!form || !status) return;
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(form).entries());
      status.textContent = 'Sending…';
      try {
        const response = await fetch(url, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json', 'X-RMR-Request': '1'},
          body: JSON.stringify(data)
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || 'Unable to submit form');
        form.reset(); status.textContent = success;
      } catch (error) { status.textContent = error.message || 'Unable to submit form.'; }
    });
  };
  submit(document.querySelector('#lead-form'), document.querySelector('#form-status'), `/api/public/sites/${encodeURIComponent(slug)}/leads`, 'Thank you. Your request has been received.');
  submit(document.querySelector('#appointment-form'), document.querySelector('#appointment-status'), `/api/public/sites/${encodeURIComponent(slug)}/appointments`, 'Thank you. Your appointment request has been received.');
})();
