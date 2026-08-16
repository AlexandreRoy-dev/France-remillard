const AGENT_EMAIL = "fremillard@royallepage.ca";

function setError(field, message) {
  const wrap = field.closest(".field");
  const error = wrap ? wrap.querySelector(".field__error") : null;
  field.setAttribute("aria-invalid", message ? "true" : "false");
  if (error) error.textContent = message || "";
}

function isEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function validate(form) {
  let valid = true;
  const name = form.elements.namedItem("name");
  const email = form.elements.namedItem("email");
  const phone = form.elements.namedItem("phone");
  const message = form.elements.namedItem("message");
  const consent = form.elements.namedItem("consent");

  if (name instanceof HTMLInputElement) {
    const ok = name.value.trim().length >= 2;
    setError(name, ok ? "" : "Indiquez votre prénom et votre nom.");
    valid = valid && ok;
  }

  if (email instanceof HTMLInputElement) {
    const ok = isEmail(email.value.trim());
    setError(email, ok ? "" : "Entrez une adresse courriel valide.");
    valid = valid && ok;
  }

  if (phone instanceof HTMLInputElement && phone.value.trim()) {
    const ok = phone.value.trim().replace(/\D/g, "").length >= 10;
    setError(phone, ok ? "" : "Entrez un numéro à 10 chiffres.");
    valid = valid && ok;
  } else if (phone instanceof HTMLInputElement) {
    setError(phone, "");
  }

  if (message instanceof HTMLTextAreaElement) {
    const ok = message.value.trim().length >= 10;
    setError(message, ok ? "" : "Décrivez votre projet en quelques mots.");
    valid = valid && ok;
  }

  if (consent instanceof HTMLInputElement) {
    const ok = consent.checked;
    setError(consent, ok ? "" : "Le consentement est requis pour vous répondre.");
    valid = valid && ok;
  }

  return valid;
}

function buildMailto(form) {
  const value = (name) => {
    const field = form.elements.namedItem(name);
    return field && "value" in field ? String(field.value).trim() : "";
  };

  const broker = form.querySelector('input[name="broker"]:checked');
  const brokerLabel = broker instanceof HTMLInputElement ? broker.value : "Non précisé";

  const lines = [
    `Nom: ${value("name")}`,
    `Courriel: ${value("email")}`,
    `Téléphone: ${value("phone") || "Non fourni"}`,
    `Travaille déjà avec un courtier: ${brokerLabel}`,
    "",
    value("message"),
  ];

  const subject = encodeURIComponent(`Message du site, ${value("name")}`);
  const body = encodeURIComponent(lines.join("\n"));
  return `mailto:${AGENT_EMAIL}?subject=${subject}&body=${body}`;
}

export function initForm() {
  const form = document.querySelector("[data-contact-form]");
  if (!(form instanceof HTMLFormElement)) return;

  const status = form.querySelector("[data-form-status]");
  const submit = form.querySelector("[type='submit']");

  form.addEventListener("submit", (event) => {
    event.preventDefault();

    const honeypot = form.elements.namedItem("company");
    if (honeypot instanceof HTMLInputElement && honeypot.value.trim()) {
      return;
    }

    if (status) {
      status.textContent = "";
      status.className = "form-status";
    }

    if (!validate(form)) {
      if (status) {
        status.textContent = "Veuillez corriger les champs indiqués.";
        status.classList.add("is-error");
      }
      const firstInvalid = form.querySelector("[aria-invalid='true']");
      if (firstInvalid instanceof HTMLElement) firstInvalid.focus();
      return;
    }

    if (submit instanceof HTMLButtonElement) {
      submit.disabled = true;
    }

    window.location.href = buildMailto(form);

    if (status) {
      status.textContent =
        "Votre message est prêt. Confirmez l'envoi dans votre application de courriel.";
      status.classList.add("is-success");
    }

    window.setTimeout(() => {
      if (submit instanceof HTMLButtonElement) submit.disabled = false;
    }, 1200);
  });
}
