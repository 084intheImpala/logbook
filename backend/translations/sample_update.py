"""Updating samples from a file: on the Import page and a sample's own (samples/update.html, _update_diff.html, backend/sample_update.py)."""
PT = {
    # The sample page
    "Update from a file": "Atualizar a partir de um ficheiro",
    "Compare this sample with a .json or .zip file, as for Import, and choose which differences to take":
        "Comparar esta amostra com um ficheiro .json ou .zip, como em Importar, e escolher que diferenças aceitar",
    # The page
    "Update {sample} from a file": "Atualizar {sample} a partir de um ficheiro",
    "Upload this sample written up as for Import (a .json file, or a .zip with its photos and files). It is compared with the sample and its pieces, and you choose which differences to take: what the file adds or changes starts ticked, what it would remove doesn't. Nothing is saved until you confirm.":
        "Envie esta amostra descrita como para Importar (um ficheiro .json, ou um .zip com as fotografias e ficheiros). É comparada com a amostra e os seus pedaços, e escolhe que diferenças aceitar: o que o ficheiro acrescenta ou muda começa assinalado, o que retiraria não. Nada é guardado até confirmar.",
    "If the file has several samples, the one with this sample's label is used. The ID, owner and type stay as they are.":
        "Se o ficheiro tiver várias amostras, usa-se a que tem o rótulo desta. O ID, o responsável e o tipo ficam como estão.",
    "Compare": "Comparar",
    "Uploading and comparing. A big zip can take a few minutes.":
        "A enviar e a comparar. Um zip grande pode demorar alguns minutos.",
    "Nothing was changed. Fix these and upload the file again:":
        "Nada foi alterado. Corrija isto e envie o ficheiro outra vez:",
    "The file and the sample are the same: nothing to change.":
        "O ficheiro e a amostra são iguais: nada a alterar.",
    "Worth a look (these don't stop the update):": "A ver (não impedem a atualização):",
    "1 difference:": "1 diferença:",
    "{n} differences:": "{n} diferenças:",
    "Tick all": "Assinalar todas",
    "Untick all": "Desmarcar todas",
    "Make the ticked changes": "Fazer as alterações assinaladas",
    "Saving the changes and their files. A big zip can take a few minutes.":
        "A guardar as alterações e os ficheiros. Um zip grande pode demorar alguns minutos.",
    "new in the file": "nova no ficheiro",
    "not in the file": "não está no ficheiro",
    "not in the file; a cut is kept (its pieces inherit what's before it)":
        "não está no ficheiro; um corte fica (os pedaços herdam o que está antes dele)",
    "changed": "alterada",
    "The same in the file and here:": "Iguais no ficheiro e aqui:",
    "New pieces": "Pedaços novos",
    "Pieces not in the file, left as they are:": "Pedaços que não estão no ficheiro, deixados como estão:",
    # Messages
    "That upload has expired or was already used; upload the file again.":
        "Esse envio expirou ou já foi usado; envie o ficheiro outra vez.",
    "Nothing was ticked, so nothing changed.": "Nada foi assinalado, por isso nada mudou.",
    "Updated from the file: 1 change made.": "Atualizada a partir do ficheiro: 1 alteração feita.",
    "Updated from the file: {n} changes made.": "Atualizada a partir do ficheiro: {n} alterações feitas.",
    "A piece is updated with the file of the sample it was cut from.":
        "Um pedaço atualiza-se com o ficheiro da amostra de onde foi cortado.",
    "The file has {n} samples: it should have one, or one labelled {label}.":
        "O ficheiro tem {n} amostras: deve ter uma, ou uma com o rótulo {label}.",
    "The file has no sample.": "O ficheiro não tem nenhuma amostra.",
    "the file says {type}; an update doesn't change the type (Edit does)":
        "o ficheiro diz {type}; uma atualização não muda o tipo (Editar muda)",
    "only the owner can change the visibility": "só o responsável pode mudar a visibilidade",
    "the file names another owner; an update doesn't change it (Edit does)":
        "o ficheiro indica outro responsável; uma atualização não o muda (Editar muda)",
    "you can't edit this piece, so it isn't compared": "não pode editar este pedaço, por isso não é comparado",
    # The differences
    "yes": "sim",
    "no": "não",
    "Label": "Rótulo",
    "Description": "Descrição",
    "Film material": "Material do filme",
    "External ID": "ID externo",
    "Substrate dimensions": "Dimensões do substrato",
    "Substrate": "Substrato",
    "Project": "Projeto",
    "Visibility": "Visibilidade",
    "Tags": "Etiquetas",
    "Reference sample": "Amostra de referência",
    "Study": "Estudo",
    "File": "Ficheiro",
    "Date": "Data",
    "Notes": "Notas",
    "Procedure followed": "Procedimento seguido",
    "Method": "Método",
    "Not in the file: delete it": "Não está no ficheiro: apagar",
    "Add this entry": "Acrescentar esta entrada",
    "{n} pieces": "{n} pedaços",
    "{n} files": "{n} ficheiros",
    "{n} entries": "{n} entradas",
    "Piece": "Pedaço",
    "Reference piece": "Pedaço de referência",
    "Order of the timeline": "Ordem da cronologia",
    "as it is": "como está",
    "as in the file": "como no ficheiro",
    "Layer": "Camada",
    "on the substrate": "sobre o substrato",
    "on {entry}": "sobre {entry}",
    "on top": "por cima de tudo",
    "the new {type}": "a nova {type}",
    "Done together": "Feito em conjunto",
    "one run with 1 other entry in the file": "uma execução com mais 1 entrada do ficheiro",
    "one run with {n} other entries in the file": "uma execução com mais {n} entradas do ficheiro",
    # On the Import page
    "Update samples already here (same label)": "Atualizar as amostras que já cá estão (mesmo rótulo)",
    "A sample in the file whose label (or code) matches a sample here that you can edit is compared with it, and you choose which differences to take, instead of importing it again":
        "Uma amostra do ficheiro cujo rótulo (ou código) corresponda a uma amostra daqui que pode editar é comparada com ela, e escolhe que diferenças aceitar, em vez de a importar outra vez",
    "Samples already here are compared with the file: tick the changes to make.":
        "As amostras que já cá estão são comparadas com o ficheiro: assinale as alterações a fazer.",
    "Already here, compared with the file:": "Já cá estão, comparadas com o ficheiro:",
    "1 difference": "1 diferença",
    "{n} differences": "{n} diferenças",
    "Import 1 sample and make the ticked changes": "Importar 1 amostra e fazer as alterações assinaladas",
    "Import {n} samples and make the ticked changes": "Importar {n} amostras e fazer as alterações assinaladas",
    "The samples in the file are already here, with no differences: nothing to import or change.":
        "As amostras do ficheiro já cá estão, sem diferenças: nada a importar nem a alterar.",
    "Updated 1 sample already here: 1 change made.": "Atualizada 1 amostra que já cá estava: 1 alteração feita.",
    "Updated {samples} samples already here: {n} changes made.":
        "Atualizadas {samples} amostras que já cá estavam: {n} alterações feitas.",
    '"code" names a sample to update: tick "Update samples already here"':
        '"code" indica uma amostra a atualizar: assinale "Atualizar as amostras que já cá estão"',
    "no sample {code} to update (give the ID of a sample, not of a piece)":
        "não há nenhuma amostra {code} para atualizar (indique o ID de uma amostra, não de um pedaço)",
    "you can't edit {code}, so it can't be updated": "não pode editar {code}, por isso não pode ser atualizada",
    'several samples are labelled {label} ({codes}): add "code" with the ID of the one to update':
        'várias amostras têm o rótulo {label} ({codes}): acrescente "code" com o ID da que quer atualizar',
    "{code} is in the file twice": "{code} está duas vezes no ficheiro",
}
