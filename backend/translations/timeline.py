"""Process step and analysis forms, their routers, and the seeded step /
analysis types (names, descriptions, parameter labels and placeholders)."""
PT = {
    # steps/form.html, analyses/form.html
    "Samples": "Amostras",
    "Edit Step": "Editar passo",
    "Add Step": "Adicionar passo",
    "Edit Process Step": "Editar passo de processo",
    "Add Process Step": "Adicionar passo de processo",
    "Step Type": "Tipo de passo",
    "Edit Analysis": "Editar análise",
    "Add Analysis": "Adicionar análise",
    "Edit {name}": "Editar {name}",
    "Analysis Type": "Tipo de análise",
    "select": "escolha",
    "Performed by": "Realizado por",
    "Name": "Nome",
    "Date & Time": "Data e hora",
    "optional": "opcional",
    "Parameters": "Parâmetros",
    "Add fields from type": "Adicionar campos do tipo",
    "One parameter per line:": "Um parâmetro por linha:",
    "key: value": "chave: valor",
    "keys": "chaves",
    "Notes": "Notas",
    "Additional observations": "Observações adicionais",
    "Instrument used, conditions, observations…": "Instrumento utilizado, condições, observações…",
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

    # Labels also used on the forms. Step/analysis types, techniques and
    # parameters themselves stay in English (technical terms).
    "Technique": "Técnica",
    "Method": "Método",
    "Description": "Descrição",
}
