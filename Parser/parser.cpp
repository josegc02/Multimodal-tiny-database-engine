#include<iostream>
#include "token.h"
#include "scanner.h"
#include "ast.h"
#include "parser.h"
#include <string>

using namespace std;

// =============================
// Métodos de la clase Parser
// =============================

Parser::Parser(Scanner* sc) : scanner(sc) {
    previous = nullptr;
    current = scanner->nextToken();
    if (current->type == Token::ERR) {
        throw runtime_error("Error léxico");
    }
}

bool Parser::match(Token::Type ttype) {
    if (check(ttype)) {
        advance();
        return true;
    }
    return false;
}

bool Parser::check(Token::Type ttype) {
    if (isAtEnd()) return false;
    return current->type == ttype;
}

bool Parser::advance() {
    if (!isAtEnd()) {
        Token* temp = current;
        if (previous) delete previous;
        current = scanner->nextToken();
        previous = temp;

        if (check(Token::ERR)) {
            throw runtime_error("Error lexico");
        }
        return true;
    }
    return false;
}

bool Parser::isAtEnd() {
    return (current->type == Token::END);
}


Program *Parser::parseProgram() {
    Program* p = new Program();

    while (match(Token::HASHTAG) || match(Token::ID)) {

        // ---------- #include <...> ----------
        if (previous->type == Token::HASHTAG) { 
            Libreria* lib = parseLibreria();
            p->items.push_back(lib);
        }

        // ---------- declaraciones globales (int, struct, etc.) ----------
        else if (previous->type == Token::ID) {
            string tipo   = previous->text;   // p.ej. "int" o "struct"
            string nombre;

            // esperamos:  tipo ID(...)  ó  tipo ID = ... ;  ó  tipo ID ;
            // o en el caso de struct anónimo:  struct { ... } nombre ;
            if (match(Token::ID)) {
                // caso: tipo nombre ...
                if (previous->type == Token::ID) {
                    nombre = previous->text;  // nombre de la función o variable

                    if (match(Token::LPAREN) || match(Token::ASSIGN) || match(Token::SEMICOL) || match(Token::LLAVEL) || match(Token::CORL)) {

                        // ---- función:  tipo nombre( ... ) { ... }
                        if (previous->type == Token::LPAREN) {
                            FunDec* f = parseFunDec(tipo, nombre);
                            p->items.push_back(f);
                        }

                        // ---- variable global inicializada:  tipo nombre = expr ;
                        else if (previous->type == Token::ASSIGN) {
                            Exp* init = parseCE();
                            match(Token::SEMICOL);
                            VarDec* vd = parseVarDec(tipo, nombre, /*inner_function=*/false, init);
                            p->items.push_back(vd);
                        }

                        // ---- variable global sin inicializar:  tipo nombre ;
                        else if (previous->type == Token::SEMICOL) {
                            VarDec* vd = parseVarDec(tipo, nombre, /*inner_function=*/false, nullptr);
                            p->items.push_back(vd);
                        }
                        // ---- struct global sin inicializar:  struct nombre {...};
                        else if (previous->type == Token::LLAVEL) {
                            StructDec* sd = parseStructDec(tipo,nombre, /*inner_function=*/false);
                            p->items.push_back(sd);
                        }
                        // ---- array global: int array[5];   /   int array[3] = {1,2,3};
                        else if (previous->type == Token::CORL) {
                            ArrayDec* ad = parseArrayDec(tipo, nombre, /*inner=*/false);
                            p->items.push_back(ad);
                        }
                    }
                }
            }
        }
    }

    if (!isAtEnd()) {
        throw runtime_error("Error sintactico");
    }

    cout << "Parseo exitoso" << endl;
    return p;
}


ArrayDec* Parser::parseArrayDec(string tipo, string nombre, bool inner) {
    ArrayDec* ad = new ArrayDec();
    ad->tipo = tipo;
    ad->nombre = nombre;
    ad->inner_function = inner;

    // Ya hemos consumido el token '[' en parseProgram/parseBody
    // O lo podemos consumir aquí si no se hizo antes:
    // match(Token::CORL);  // si no lo consumiste antes

    ad->size = parseCE();       // array[ <size> ]
    match(Token::CORR);

    // ¿tiene lista de inicialización?
    if (match(Token::ASSIGN)) {
        match(Token::LLAVEL);   // '{'
        // {1,2,3}   (al menos un elemento)
        if (!check(Token::LLAVER)) {
            ad->valores.push_back(parseCE());
            while (match(Token::COMA)) {
                ad->valores.push_back(parseCE());
            }
        }
        match(Token::LLAVER);   // '}'
    }

    match(Token::SEMICOL);
    return ad;
}


StructDec* Parser::parseStructDec(string tipo,string nombre, bool inner_function){
    StructDec *sd = new StructDec();
    sd->tipo = tipo;
    sd->nombre = nombre;
    sd->inner_function = inner_function;

    // Dentro de { ... } esperamos líneas tipo:
    //   int id;
    //   int grades[3];
    while (match(Token::ID)) {         // tipo del campo (int, float, etc.)
        VarDec *vd = new VarDec();
        vd->tipo = previous->text;     // "int", por ejemplo

        match(Token::ID);              // nombre del campo
        vd->nombre = previous->text;   // "id" o "grades"

        sd->declarations.push_back(vd);
        match(Token::SEMICOL);         // ';'
    }

    match(Token::LLAVER);              // '}'
    match(Token::SEMICOL);             // ';' después del struct
    return sd;
}

Libreria* Parser::parseLibreria(){
    Libreria *lib = new Libreria();
    match(Token::HASHTAG);
    match(Token::INCLUDE);
    match(Token::LE);
    match(Token::ID);
    lib->lib = previous->text;
    match(Token::GT);
    return lib;
}


VarDec* Parser::parseVarDec(string tipo,string nombre,bool inner,Exp* valor){
    VarDec *vd = new VarDec();
    vd->tipo = tipo;
    vd->nombre = nombre;
    vd->inner_function = inner;
    vd->valor = valor;
    return vd;
}

FunDec* Parser::parseFunDec(string tipo, string nombre){
    FunDec* fd = new FunDec();
    vector<string> tips;
    vector<string> vars;

    // Parámetros entre paréntesis
    if (match(Token::ID)) {
        // Primer parámetro
        if (previous->text == "int") {
            string baseType = previous->text;   // "int"

            // ---- OPCIONAL: & para referencia ----
            bool isRefParam = false;
            if (match(Token::AMP)) {           // AJUSTA Token::AMP segun tu scanner
                isRefParam = true;
            }

            match(Token::ID);                  // nombre del parámetro
            string varName = previous->text;   // "hola", "n", etc

            bool isArrayParam = false;
            // Soporte para "int& x[]" (si quisieras) o "int x[]"
            if (match(Token::CORL)) {          // '['
                match(Token::CORR);            // ']'
                isArrayParam = true;
            }

            if (isArrayParam) {
                tips.push_back(baseType + "[]");   // "int[]"
            } else if (isRefParam) {
                tips.push_back(baseType + "&");    // "int&"
            } else {
                tips.push_back(baseType);          // "int"
            }

            vars.push_back(varName);
        }

        // Parámetros adicionales separados por coma
        while (match(Token::COMA)) {
            match(Token::ID);
            if (previous->text == "int") {
                string baseType = previous->text;

                bool isRefParam = false;
                if (match(Token::AMP)) {        // AJUSTA Token::AMP
                    isRefParam = true;
                }

                match(Token::ID);
                string varName = previous->text;

                bool isArrayParam = false;
                if (match(Token::CORL)) {       // '['
                    match(Token::CORR);         // ']'
                    isArrayParam = true;
                }

                if (isArrayParam) {
                    tips.push_back(baseType + "[]");
                } else if (isRefParam) {
                    tips.push_back(baseType + "&");
                } else {
                    tips.push_back(baseType);
                }
                vars.push_back(varName);
            }
        }
    }

    match(Token::RPAREN);
    match(Token::LLAVEL);
    Body* body = parseBody();
    match(Token::LLAVER);

    fd->nombre    = nombre;
    fd->tipo      = tipo;
    fd->tipos     = tips;
    fd->variables = vars;
    fd->body      = body;

    return fd;
}



Body* Parser::parseBody() {
    Body* b = new Body();
    list<Node*> items;   

    while (match(Token::ID) || match(Token::PRINT) || match(Token::RETURN) 
        || match(Token::IF) || match(Token::WHILE)) {

        if (previous->type == Token::ID && 
            (previous->text == "int" || previous->text == "struct" || previous->text == "string")) {

            string tipo = previous->text;

            // ===== int ... =====
            if (tipo == "int") {
                match(Token::ID);           // nombre
                string nombre = previous->text;
                
                 // --- Caso: int x = expr;
                if (match(Token::ASSIGN)) {
                    // int nombre = expr;
                    // 1) declaración local sin inicializador
                    VarDec* vd = parseVarDec(tipo, nombre, /*inner=*/true, /*valor=*/parseCE());
                    items.push_back(vd);

                    // 2) asignación explícita
                    match(Token::SEMICOL);

                }
                 // --- Caso: int x;
                else if (match(Token::SEMICOL)) {
                    // int nombre;
                    VarDec* vd = parseVarDec(tipo, nombre, /*inner=*/true, /*valor=*/nullptr);
                    items.push_back(vd);
                }
                // --- Caso: int array[...];
                else if (check(Token::CORL)) {
                    match(Token::CORL); // consumimos '['
                    ArrayDec* ad = parseArrayDec(tipo, nombre, /*inner=*/true);
                    items.push_back(ad);
                }
                else {
                    throw runtime_error("Error sintactico en declaracion local");
                }
            }

            // ===== struct ... =====
            else if (tipo == "struct") {
                 // leemos el nombre del struct
                match(Token::ID);
                string structName = previous->text;

                // CASO A: definición local de struct: struct hola { ... };
                if (check(Token::LLAVEL)) {
                    match(Token::LLAVEL);
                    StructDec* sd = parseStructDec(tipo, structName, /*inner_function=*/true);
                    items.push_back(sd);
                }
                // CASO B: variable de tipo struct hola: struct hola ap;
                else {
                    string fullType = tipo + " " + structName;  // "struct hola"

                    match(Token::ID);              // nombre de la variable
                    string varName = previous->text;

                    if (match(Token::SEMICOL)) {
                        // struct hola ap;
                        VarDec* vd = parseVarDec(fullType, varName, /*inner=*/true, /*valor=*/nullptr);
                        items.push_back(vd);
                    }
                    else {
                        throw runtime_error("Error sintactico en declaracion local de struct");
                    }
                }
            }
            else if (tipo == "string") {
                match(Token::ID);           // nombre
                string nombre = previous->text;
                
                // --- Caso: string x = expr;
                if (match(Token::ASSIGN)) {
                    // 1) declaración local sin inicializador en la tabla de símbolos
                    VarDec* vd = parseVarDec(tipo, nombre, /*inner=*/true, /*valor=*/nullptr);
                    items.push_back(vd);

                    // 2) asignación explícita
                    Exp* e = parseCE();     // aquí puede venir un StringExp
                    match(Token::SEMICOL);

                    AssignStm* astm = new AssignStm();
                    astm->id = nombre;
                    astm->e  = e;
                    items.push_back(astm);
                }
                // --- Caso: string x;
                else if (match(Token::SEMICOL)) {
                    VarDec* vd = parseVarDec(tipo, nombre, /*inner=*/true, /*valor=*/nullptr);
                    items.push_back(vd);
                }
                else {
                    throw runtime_error("Error sintactico en declaracion local de string");
                }
            }


        }

        // ---------- Sentencias que comienzan con un identificador ----------
        else if (previous->type == Token::ID && 
                (previous->text != "int" && previous->text != "struct" && previous->text != "string")) {

            string nombre = previous->text; // puede ser variable, función, struct, etc.

            if (check(Token::LPAREN)) {
                match(Token::LPAREN);
                FcallStm* fstm = parseFcallStm(nombre);
                items.push_back(fstm);
            }
            else if (check(Token::ASSIGN)) {
                match(Token::ASSIGN);
                AssignStm* astm = parseAssignStm(nombre);
                items.push_back(astm);
            }
            else if (check(Token::PUNTO)) {
                match(Token::PUNTO);
                AssignStructStm* asstm = parseAssignStructStm(nombre);
                items.push_back(asstm);
            }
            else if (check(Token::CORL)) {
                AssignArrayStm* aastm = parseAssignArrayStm(nombre);
                items.push_back(aastm);
            }
            else {
                throw runtime_error("Sentencia que empieza con ID no reconocida");
            }
        }

        // ---------- print(expr); ----------
        else if (previous->type == Token::PRINT) {
            PrintStm* ps = parsePrintStm();
            items.push_back(ps);
        }

        // ---------- return expr; ----------
        else if (previous->type == Token::RETURN) {
            ReturnStm* rs = parseReturnStm();
            items.push_back(rs);
        }

        // ---------- if (...) { ... } [else { ... }] ----------
        else if (previous->type == Token::IF) {
            IfStm* ifs = parseIfStm();
            items.push_back(ifs);
        }

        // ---------- while (...) { ... } ----------
        else if (previous->type == Token::WHILE) {
            WhileStm* ws = parseWhileStm();
            items.push_back(ws);
        }

        else {
            // no deberíamos caer aquí por cómo está el while,
            // pero por seguridad lo dejamos vacío
        }
    }

    b->items = items;
    return b;
}



AssignArrayStm* Parser::parseAssignArrayStm(string nombre) {
    AssignArrayStm* as = new AssignArrayStm();
    as->array_id = nombre;

    match(Token::CORL);          // '['
    as->index = parseCE();
    match(Token::CORR);          // ']'

    match(Token::ASSIGN);
    as->new_value = parseCE();
    match(Token::SEMICOL);

    return as;
}

AssignStructStm* Parser::parseAssignStructStm(string nombre){
    AssignStructStm * asstm = new AssignStructStm();
    asstm->struc_id = nombre;

    match(Token::ID);
    asstm->var_id = previous->text;   // "id" o "grades"
    match(Token::ASSIGN);
    asstm->e = parseCE();
    match(Token::SEMICOL);
    return asstm;
}

FcallStm* Parser::parseFcallStm(std::string nombre) {
    FcallStm* fstm = new FcallStm();
    fstm->nombre = nombre;
    std::vector<Exp*> argumentos;

    // average(...)
    if (!check(Token::RPAREN)) {
        argumentos.push_back(parseCE());
        while (match(Token::COMA)) {
            argumentos.push_back(parseCE());
        }
    }

    match(Token::RPAREN);
    match(Token::SEMICOL);
    fstm->argumentos = argumentos;
    return fstm;
}



AssignStm* Parser::parseAssignStm(string nombre){
    AssignStm* astm = new AssignStm();
    astm->id = nombre;
    astm->e = parseCE();
    match(Token::SEMICOL);
    return astm;
}

WhileStm* Parser::parseWhileStm(){
    WhileStm* wstm = new WhileStm();
    match(Token::LPAREN);
    Exp* e = parseCE();
    match(Token::RPAREN);
    match(Token::LLAVEL);
    Body* caso1 = parseBody();
    match(Token::LLAVER);
    wstm->condicion = e;
    wstm->caso1 = caso1;
    return wstm;
}

IfStm* Parser::parseIfStm(){
    IfStm* ifstm = new IfStm();
    match(Token::LPAREN);
    Exp* e = parseCE();
    match(Token::RPAREN); // ( )
    Body* caso1;
    match(Token::LLAVEL); // { 
    caso1 = parseBody();
    match(Token::LLAVER); // }
    Body* caso2;
    if(match(Token::ELSE)){ // else 
        match(Token::LLAVEL); // { 
        caso2 = parseBody();
        match(Token::LLAVER); // }
    }
    ifstm->condicion = e;
    ifstm->caso1 = caso1;
    ifstm->caso2 = caso2;

    return ifstm;
}

ReturnStm* Parser::parseReturnStm(){
    ReturnStm* rs = new ReturnStm();
    rs->e = parseCE();
    match(Token::SEMICOL);

    return rs;
}

PrintStm* Parser::parsePrintStm(){
    PrintStm* ps = new PrintStm();
    match(Token::LPAREN);
    ps->e = parseCE();
    match(Token::RPAREN);
    match(Token::SEMICOL);
    return ps;
}


Exp* Parser::parseCE() {
    Exp* l = parseBE();

    if (match(Token::LE) || match(Token::GT) || match(Token::EQUAL) || match(Token::NEQUAL)) {
        BinaryOp op;
        if (previous->type == Token::LE)
            op = LE_OP;
        else if (previous->type == Token::GT){ 
            op = GT_OP;
        } else if (previous->type == Token::EQUAL){
            op = EQUAL_OP;
        } else if (previous->type == Token::NEQUAL){
            op = NEQUAL_OP;
        }

        Exp* r = parseBE();
        l = new BinaryExp(l, r, op);
    }

    if (match(Token::QUESTION)) {      
        Ternaria* t = new Ternaria();
        t->condicion = l;              

        t->then_branch = parseCE();

        match(Token::DOSPUNTOS);

        t->else_branch = parseCE();

        l = t;
    }

    return l;
}


Exp* Parser::parseBE() {
    Exp* l = parseE();
    while (match(Token::PLUS) || match(Token::MINUS)) {
        BinaryOp op;
        if (previous->type == Token::PLUS){
            op = PLUS_OP;
        }
        else{
            op = MINUS_OP;
        }
        Exp* r = parseE();
        l = new BinaryExp(l, r, op);
    }
    return l;
}


Exp* Parser::parseE() {
    Exp* l = parseT();
    while (match(Token::MUL) || match(Token::DIV)) {
        BinaryOp op;
        if (previous->type == Token::MUL){
            op = MUL_OP;
        }
        else{
            op = DIV_OP;
        }
        Exp* r = parseT();
        l = new BinaryExp(l, r, op);
    }
    return l;
}


Exp* Parser::parseT() {
    Exp* l = parseF();
    if (match(Token::POW)) {
        BinaryOp op = POW_OP;
        Exp* r = parseF();
        l = new BinaryExp(l, r, op);
    }
    return l;
}

Exp* Parser::parseF() {
    Exp* e;
    string nom;
    if (match(Token::NUM)) {
        return new NumberExp(stoi(previous->text));
    }
    else if (match(Token::TRUE)) {
        return new NumberExp(1);
    }
    else if (match(Token::FALSE)) {
        return new NumberExp(0);
    }
    else if (match(Token::LPAREN))
    {
        e = parseCE();
        match(Token::RPAREN);
        return e;
    }
    else if (match(Token::STRING_LITERAL)) {   // <-- ajusta el nombre del token
        // previous->text debe contener el contenido (con o sin comillas,
        // según tu scanner; si sigue con comillas, luego lo limpias en el codegen o aquí)
        return new StringExp(previous->text);
    }
    else if (match(Token::ID)) {
        nom = previous->text;
        if(check(Token::LPAREN)) {
            match(Token::LPAREN);
            FcallExp* fcall = new FcallExp();
            fcall->nombre = nom;
            // argumentos opcionales
            if (!check(Token::RPAREN)) {
                fcall->argumentos.push_back(parseCE());
                while (match(Token::COMA)) {
                    fcall->argumentos.push_back(parseCE());
                }
            }
            match(Token::RPAREN);
            return fcall;
        }
        else if (check(Token::PUNTO)) {
            match(Token::PUNTO);
            match(Token::ID);
            std::string field = previous->text;   // "id" o "grades"

            // caso: st.id (campo escalar)
            StructAccessExp* sae = new StructAccessExp();
            sae->struc_id = nom;
            sae->field_id = field;
            return sae;
        }
        else if (check(Token::CORL)) {
            ArrayAccessExp* aexp = new ArrayAccessExp();
            aexp->array_id = nom;
            match(Token::CORL);
            aexp->index = parseCE();
            match(Token::CORR);
            return aexp;
        }
        else {
            return new IdExp(nom);
            }
    }
    else {
        throw runtime_error("Error sintáctico");
    }
    
}