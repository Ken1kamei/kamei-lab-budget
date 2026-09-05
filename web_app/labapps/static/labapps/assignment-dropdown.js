document.querySelectorAll("[data-assignment-dropdown]").forEach((dropdown) => {
  const summary = dropdown.querySelector("[data-assignment-summary]");
  const choices = dropdown.querySelectorAll('input[type="checkbox"]');

  const updateSummary = () => {
    const selectedCount = Array.from(choices).filter((choice) => choice.checked).length;
    summary.textContent = selectedCount ? `${selectedCount} selected` : "None selected";
  };

  dropdown.addEventListener("change", updateSummary);
  updateSummary();
});
