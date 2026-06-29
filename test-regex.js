const text = "Ecco la risposta [1] e [2]. Non questa [[3]](#source-3) e nemmeno [4](url)";
const replaced = text.replace(/(?<!\[)\[(\d+)\](?!\]|\()/g, "[[$1]](#source-$1)");
console.log(replaced);
