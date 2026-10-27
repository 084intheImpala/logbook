PT = {
    # sample ID change (admin)
    "Change the sample ID": "Alterar o ID da amostra",
    "admin only": "só administradores",
    "Change this sample's ID? Its pieces and its files folder are renamed too, and the owner is emailed.":
        "Alterar o ID desta amostra? As peças e a pasta de ficheiros também são renomeadas, e o dono recebe um email.",
    "For a sample created under the wrong owner or type. It gets the next free number under the initials or project code you choose. The old ID is kept on the sample and never reused.":
        "Para uma amostra criada com o dono ou o tipo errados. Recebe o próximo número livre sob as iniciais ou o código de projeto escolhidos. O ID antigo fica registado na amostra e nunca é reutilizado.",
    "Number it under": "Numerar sob",
    "Researchers": "Investigadores",
    "or type the ID": "ou escreva o ID",
    "Change ID": "Alterar ID",
    "Previously": "Anteriormente",
    "ID changed from {old} to {new}.": "ID alterado de {old} para {new}.",
    "Choose whose initials or which project's code to use, or type an ID.":
        "Escolha as iniciais ou o código de projeto a usar, ou escreva um ID.",
    "{name} has no email address, so tell them about the new ID.":
        "{name} não tem endereço de email; avise-o do novo ID.",
    "Couldn't email {name} ({error}); tell them about the new ID.":
        "Não foi possível enviar email a {name} ({error}); avise-o do novo ID.",
    "This sample has no ID to change.": "Esta amostra não tem ID para alterar.",
    "This sample is a piece; change the ID of the sample it was cut from instead.":
        "Esta amostra é uma peça; altere antes o ID da amostra de que foi cortada.",
    "An ID looks like ABC-2026-001: 2–6 capital letters or digits, the year and a number.":
        "Um ID tem a forma ABC-2026-001: 2–6 letras maiúsculas ou algarismos, o ano e um número.",
    "That is already this sample's ID.": "Esse já é o ID desta amostra.",
    # samples/form.html
    "Edit {sample}": "Editar {sample}",
    "Edit": "Editar",
    "New Sample": "Nova amostra",
    "The sample ID doesn't change.": "O ID da amostra não muda.",
    "The ID is generated when you save:": "O ID é gerado quando guardar:",
    "Sample type": "Tipo de amostra",
    "Label": "Rótulo",
    "optional, your own description": "opcional, a sua própria descrição",
    "e.g. waveguide test, batch 2": "ex.: teste de guia de onda, lote 2",
    "Substrate": "Substrato",
    "choose from the library": "escolha da biblioteca",
    "The substrate library is empty.": "A biblioteca de substratos está vazia.",
    "Missing one?": "Falta algum?",
    "Add a substrate": "Adicione um substrato",
    "(opens in a new tab), then reload this page.": "(abre num novo separador) e depois recarregue esta página.",
    "Dimensions": "Dimensões",
    "e.g. 5×5 mm": "ex.: 5×5 mm",
    "Film material": "Material do filme",
    "optional": "opcional",
    "e.g. Ga2O3, TiN": "ex.: Ga2O3, TiN",
    "External ID": "ID externo",
    "Product / batch no.": "N.º de produto / lote",
    "Supplier": "Fornecedor",
    "Spec sheet": "Ficha técnica",
    "PDF or photo": "PDF ou fotografia",
    "Attached:": "Anexos:",
    "Description": "Descrição",
    "Tags": "Etiquetas",
    "comma-separated; pick existing ones when you can": "separadas por vírgulas; escolha etiquetas existentes sempre que possível",
    "e.g. Ga2O3, nanoparticles": "ex.: Ga2O3, nanopartículas",
    "Researcher": "Investigador(a)",
    "who the sample belongs to": "a quem pertence a amostra",
    "who the sample belongs to; you can give it to someone else": "a quem pertence a amostra; pode entregá-la a outra pessoa",
    "me": "eu",
    "The sample goes straight to them.": "A amostra passa diretamente para essa pessoa.",
    "They'll get an email asking them to confirm it. You keep edit access, and if they decline it comes back to you.":
        "Essa pessoa receberá um email a pedir que a confirme. Mantém o acesso de edição e, se ela recusar, a amostra volta para si.",
    "They'll get an email asking them to confirm it. You get edit access, and if they decline it becomes yours.":
        "Essa pessoa receberá um email a pedir que a confirme. Fica com acesso de edição e, se ela recusar, a amostra passa a ser sua.",
    "The ID stays the same.": "O ID mantém-se.",
    "Owner": "Responsável",
    "admin only; controls who can see details": "apenas administradores; controla quem pode ver os detalhes",
    "No owner (open to everyone)": "Sem responsável (aberta a todos)",
    "Save changes": "Guardar alterações",
    "Create sample": "Criar amostra",
    "Cancel": "Cancelar",

    # samples/cut.html
    "Cut {sample}": "Dividir {sample}",
    "Samples": "Amostras",
    "Cut into pieces": "Dividir em pedaços",
    "Cut {sample} into pieces": "Dividir {sample} em pedaços",
    "Each piece becomes its own sample and inherits {sample}'s history up to this cut.":
        "Cada pedaço torna-se uma amostra própria e herda o historial de {sample} até esta divisão.",
    "{sample} itself stays in the logbook and can keep getting new steps.":
        "A amostra {sample} continua no logbook e pode continuar a receber novos passos.",
    "Number of pieces": "Número de pedaços",
    "Method": "Método",
    "ID": "ID",
    "Also keep a reference piece": "Guardar também um pedaço de referência",
    "listed with the other pieces, marked as Reference": "listado com os outros pedaços, marcado como Referência",
    "e.g. reference": "ex.: referência",
    "Notes": "Notas",
    "Optional": "Opcional",
    "Pieces copy the sample type, substrate, film and tags, and are shared with the same people as {sample}.":
        "Os pedaços copiam o tipo de amostra, o substrato, o filme e as etiquetas, e são partilhados com as mesmas pessoas que {sample}.",
    "Each piece belongs to the researcher chosen for it (by default whoever cut it).":
        "Cada pedaço pertence ao/à investigador(a) escolhido(a) para ele (por omissão, quem o cortou).",
    "Cut by": "Cortado por",
    "Anyone else you give a piece to gets an email asking them to confirm it.":
        "Qualquer outra pessoa a quem entregue um pedaço receberá um email a pedir que o confirme.",
    "{name} keeps edit access to pieces given to someone else.":
        "{name} mantém o acesso de edição aos pedaços entregues a outra pessoa.",

    # backend/routers/samples.py
    "Choose the substrate from the library (add it on the Substrates tab if it's missing).":
        "Escolha o substrato da biblioteca (adicione-o no separador Substratos se não existir).",
    "A commercial sample needs a description.": "Uma amostra comercial precisa de uma descrição.",
    "A commercial sample needs its spec sheet (PDF or photo).":
        "Uma amostra comercial precisa da sua ficha técnica (PDF ou fotografia).",
    "That researcher hasn't set their initials yet, so their samples can't get an ID.":
        "Esse(a) investigador(a) ainda não definiu as suas iniciais, pelo que as suas amostras não podem receber um ID.",
    "Created for {name}. They'll be asked to confirm it; meanwhile you can edit it.":
        "Criada para {name}, a quem será pedido que a confirme; entretanto, pode editá-la.",
    "Sample confirmed: it's now in your samples.": "Amostra confirmada: já está nas suas amostras.",
    "Declined: {sample} now belongs to {name}.": "Recusada: {sample} pertence agora a {name}.",
    "Given to {name}. They'll be asked to confirm it; you keep edit access.":
        "Entregue a {name}, a quem será pedido que a confirme; mantém o acesso de edição.",
    "Can't delete: 1 piece was cut from this sample and inherits its history. Delete the piece first.":
        "Não é possível eliminar: esta amostra foi dividida e 1 pedaço herda o seu historial. Elimine primeiro o pedaço.",
    "Can't delete: {n} pieces were cut from this sample and inherit its history. Delete the pieces first.":
        "Não é possível eliminar: esta amostra foi dividida e {n} pedaços herdam o seu historial. Elimine primeiro os pedaços.",
    "Cut into at least one piece.": "Divida em pelo menos um pedaço.",
    "Cut into 1 piece.": "Dividida em 1 pedaço.",
    "Cut into {n} pieces.": "Dividida em {n} pedaços.",
    "{name} will be asked to confirm theirs.": "Será pedido a {name} que confirme os seus pedaços.",
    "{names} will be asked to confirm theirs.": "Será pedido a {names} que confirmem os respetivos pedaços.",
    "{name} has no email address, so tell them to confirm it on the site.":
        "{name} não tem endereço de email; peça-lhe que a confirme no site.",
    "Couldn't email {name} ({error}); tell them to confirm it on the site.":
        "Não foi possível enviar email a {name} ({error}); peça-lhe que a confirme no site.",
    "Shared 1 sample with {name} (edit).": "1 amostra partilhada com {name} (edição).",
    "Shared {n} samples with {name} (edit).": "{n} amostras partilhadas com {name} (edição).",
    "Shared 1 sample with {name} (view).": "1 amostra partilhada com {name} (visualização).",
    "Shared {n} samples with {name} (view).": "{n} amostras partilhadas com {name} (visualização).",
    "Skipped 1 you don't own.": "Foi ignorada 1 que não lhe pertence.",
    "Skipped {n} you don't own.": "Foram ignoradas {n} que não lhe pertencem.",
}
