"""Planned entries, the deposition duration calculator, and the compact
parameter filters on the search page."""
PT = {
    # entries/form.html
    "Plan a Process Step": "Planear um passo de processo",
    "Plan an Analysis": "Planear uma análise",
    "Marking a planned entry as done: check the values, the date included, and fill in what was only known on the day (for a deposition, the base and working pressure).":
        "Marcar uma entrada planeada como feita: confirme os valores, incluindo a data, e preencha o que só se soube no dia (numa deposição, a pressão de base e a de trabalho).",
    "Planned, not done yet": "Planeado, ainda não feito",
    "Shown on the sample's timeline as planned, with the date it's planned for; left out of search, exports and deposition rates until it's marked done.":
        "Aparece na cronologia da amostra como planeado, com a data para que está planeado; fica fora da pesquisa, das exportações e das taxas de deposição até ser marcado como feito.",
    "Use the last known rate": "Usar a última taxa conhecida",
    "Fill in the target thickness and the rate to work it out.": "Preencha a espessura pretendida e a taxa para a calcular.",
    "Worked out: {nm} nm ÷ {rate} nm/min.": "Calculada: {nm} nm ÷ {rate} nm/min.",
    "see it": "ver",
    "Couldn't get the last rate.": "Não foi possível obter a última taxa.",
    # Deposition fields (seed_data.py, migration 0016)
    "Target thickness": "Espessura pretendida",
    "Rate used for the time": "Taxa usada para o tempo",
    "last known rate, or typed": "última taxa conhecida, ou introduzida",
    # routers/steps.py (last known rate)
    "Choose the machine, target, gas, gas flow or power first.":
        "Escolha primeiro a máquina, o alvo, o gás, o fluxo de gás ou a potência.",
    "No deposition with these conditions has a rate yet.": "Nenhuma deposição com estas condições tem ainda taxa.",
    "{rate} nm/min ({how}), from {sample} on {date}: {conditions}":
        "{rate} nm/min ({how}), de {sample} em {date}: {conditions}",
    # samples/detail.html
    "Not done yet: left out of search, exports and deposition rates until it's marked done":
        "Ainda não feito: fica fora da pesquisa, das exportações e das taxas de deposição até ser marcado como feito",
    "Planned": "Planeado",
    "for {date}": "para {date}",
    "Mark as done": "Marcar como feito",
    "A step to do later, e.g. a deposition with its duration worked out from the target thickness":
        "Um passo para fazer mais tarde, p. ex. uma deposição com a duração calculada a partir da espessura pretendida",
    "Plan a step": "Planear um passo",
    # search/index.html
    "Parameters no entry has are left out.": "Os parâmetros que nenhuma entrada tem não aparecem.",
}
