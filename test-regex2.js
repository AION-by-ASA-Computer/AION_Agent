const text = "Ecco [1] e [2]. Non [[3]] e nemmeno [4](url) e a[5]b.";
console.log(text.replace(/(^|[^\[])\[(\d+)\](?!\(|\])/g, "$1[[$2]](#source-$2)"));
