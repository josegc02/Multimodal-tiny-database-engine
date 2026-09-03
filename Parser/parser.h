#ifndef PARSER_H       
#define PARSER_H

#include "scanner.h"    // Incluye la definición del escáner (provee tokens al parser)
#include "ast.h"        // Incluye las definiciones para construir el Árbol de Sintaxis Abstracta (AST)

class Parser {
private:
    Scanner* scanner;       // Puntero al escáner, de donde se leen los tokens
    Token *current, *previous; // Punteros al token actual y al anterior
    bool match(Token::Type ttype);   // Verifica si el token actual coincide con un tipo esperado y avanza si es así
    bool check(Token::Type ttype);   // Comprueba si el token actual es de cierto tipo, sin avanzar
    bool advance();                  // Avanza al siguiente token
    bool isAtEnd();                  // Comprueba si ya se llegó al final de la entrada
public:
    Parser(Scanner* scanner);       
    Program* parseProgram();
    Libreria* parseLibreria();
    VarDec* parseVarDec(string tipo,string nombre,bool inner,Exp* valor);
    FunDec* parseFunDec(string tipo,string nombre);
    AssignStructStm* parseAssignStructStm(string nombre);
    ArrayDec* parseArrayDec(std::string tipo, std::string nombre, bool inner);
    AssignArrayStm* parseAssignArrayStm(std::string nombre);
    Body* parseBody();
    WhileStm* parseWhileStm();
    IfStm* parseIfStm();
    ReturnStm* parseReturnStm();
    PrintStm* parsePrintStm();
    AssignStm* parseAssignStm(string nombre);
    FcallStm* parseFcallStm(string nombre);
    StructDec* parseStructDec(string tipo,string nombre, bool inner_function);
    Exp* parseCE();
    Exp* parseBE();
    Exp* parseE();
    Exp* parseT();
    Exp* parseF();
};

#endif // PARSER_H      