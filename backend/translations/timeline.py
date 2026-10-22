"""Process step and analysis forms, their routers, and the seeded step /
analysis types (names, descriptions, parameter labels and placeholders)."""
PT = {
    # entries/form.html (steps and analyses)
    "Samples": "Amostras",
    "Edit Process Step": "Editar passo de processo",
    "Add Process Step": "Adicionar passo de processo",
    "Step Type": "Tipo de passo",
    "Edit Analysis": "Editar análise",
    "Add Analysis": "Adicionar análise",
    "Analysis Type": "Tipo de análise",
    "select": "escolha",
    "Performed by": "Realizado por",
    "Name": "Nome",
    "optional": "opcional",
    "Parameters": "Parâmetros",
    "key: value": "chave: valor",
    "Notes": "Notas",
    "Additional observations": "Observações adicionais",
    "Photos": "Fotografias",
    "Other files": "Outros ficheiros",
    "Pick several at once; on a phone you can use the camera. Large photos are resized to {px} px.":
        "Pode escolher várias de uma vez; num telemóvel pode usar a câmara. As fotografias grandes são redimensionadas para {px} px.",
    "Data, spectra, PDFs, raw images… stored unchanged.":
        "Dados, espetros, PDFs, imagens em bruto… guardados sem alterações.",
    "Existing attachments": "Anexos existentes",
    "Remove": "Remover",
    "Remove {name}?": "Remover {name}?",
    "Save changes": "Guardar alterações",
    "Add step": "Adicionar passo",
    "Add analysis": "Adicionar análise",
    "Cancel": "Cancelar",

    # routers/steps.py
    "Can't delete this cut: {n} piece was cut here and inherits the history before it. "
    "Delete the piece first.":
        "Não é possível eliminar esta divisão: {n} pedaço resultou dela e herda o histórico anterior. "
        "Elimine primeiro o pedaço.",
    "Can't delete this cut: {n} pieces were cut here and inherit the history before it. "
    "Delete the pieces first.":
        "Não é possível eliminar esta divisão: {n} pedaços resultaram dela e herdam o histórico anterior. "
        "Elimine primeiro os pedaços.",

    # "Performed by" (_performer.html, performers.py)
    "Someone else (type the name)": "Outra pessoa (escreva o nome)",
    "They can see and edit this entry. If they get an account later, pick them here instead of the typed name.":
        "Essa pessoa pode ver e editar este registo. Se mais tarde tiver conta, escolha-a aqui em vez do nome escrito.",
    "You can see and edit the entries you performed.": "Pode ver e editar os registos que realizou.",
    "Couldn't email {name} ({error}).": "Não foi possível enviar email a {name} ({error}).",

    # Labels also used on the forms. Step/analysis types, techniques and
    # parameters themselves stay in English (technical terms).
    "Technique": "Técnica",
    "Method": "Método",
    "Description": "Descrição",

    # Structured parameters, shared dropdowns, runs (entries/form.html, _params.html)
    "Where": "Onde",
    "Add new…": "Adicionar novo…",
    "New value; it's saved for everyone": "Novo valor; fica guardado para todos",
    "Add another mode": "Adicionar outro modo",
    "Name of the new mode": "Nome do novo modo",
    "Other parameters": "Outros parâmetros",
    "Anything the fields above don't cover, one per line:": "O que os campos acima não cobrem, um por linha:",
    "Choose a type.": "Escolha um tipo.",
    "Also add to other samples": "Adicionar também a outras amostras",
    "For things done in parallel. Each ticked sample gets its own copy with the details above; files for one sample only go in the field that appears next to it.":
        "Para o que foi feito em paralelo. Cada amostra assinalada recebe a sua cópia com os dados acima; os ficheiros só de uma amostra vão no campo que aparece ao lado dela.",
    "Files only for {title}": "Ficheiros só para {title}",
    "Files for one sample only go in the field next to it.": "Os ficheiros só de uma amostra vão no campo ao lado dela.",
    "If you add this to other samples below, these photos and files go to all of them.":
        "Se adicionar isto a outras amostras abaixo, estas fotografias e ficheiros vão para todas.",
    "Filter by ID or label": "Filtrar por ID ou rótulo",
    "Also recorded on:": "Registado também em:",
    "Apply these changes to them too (not the files)": "Aplicar estas alterações também a essas (exceto ficheiros)",
    "Also on:": "Também em:",
    # Cut form
    "Photo of the pieces": "Fotografia dos pedaços",
    "Recommended: photograph the pieces with each one's letter written next to it (A, B, …), so it's clear which is which.":
        "Recomendado: fotografe os pedaços com a letra de cada um escrita ao lado (A, B, …), para se saber qual é qual.",
    # Admin: schema help
    'Field types: number (with unit), duration, text, longtext, choice (a dropdown list, "list"), variant ("options", each with its own fields), check (a tick box with "fields" shown when ticked), modes (tick several from a list, each with "fields"). See the README.':
        'Tipos de campo: number (com unidade), duration, text, longtext, choice (uma lista de opções, "list"), variant ("options", cada uma com os seus campos), check (uma caixa com "fields" que aparecem quando assinalada), modes (assinalar vários de uma lista, cada um com "fields"). Ver o README.',
    "Today": "Hoje",
    "Saving will overwrite these values on the other samples:": "Guardar vai substituir estes valores nas outras amostras:",
    "…and {n} more": "…e mais {n}",
    "Save anyway? Cancel to go back; you can untick “Apply these changes to them too”.":
        "Guardar na mesma? Cancele para voltar; pode desassinalar “Aplicar estas alterações também a essas”.",
}
