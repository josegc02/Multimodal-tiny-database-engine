#ifndef AST_H
#define AST_H

#include <string>
#include <list>
#include <vector>
using namespace std;

// =====================
//      FORWARD
// =====================
class Visitor;
class Body;

// =====================
//      NODE BASE
// =====================

class Node {
public:
    virtual int accept(Visitor* visitor) = 0;
    virtual ~Node() {}
};

// =====================
//      EXPRESSIONS
// =====================

enum BinaryOp { 
    PLUS_OP, 
    MINUS_OP, 
    MUL_OP, 
    DIV_OP,
    POW_OP,
    LE_OP,
    GT_OP,
    EQUAL_OP,
    NEQUAL_OP
};

class Exp : public Node {
public:
    virtual ~Exp() {}

    static string binopToChar(BinaryOp op) {
        switch (op) {
            case PLUS_OP:  return "+";
            case MINUS_OP: return "-";
            case MUL_OP:   return "*";
            case DIV_OP:   return "/";
            case POW_OP:   return "**";
            case LE_OP:    return "<";
            case GT_OP:    return ">";
            case EQUAL_OP: return "==";
            case NEQUAL_OP: return "!=";
            default:       return "?"; 
        }
    }
};

class BinaryExp : public Exp {
public:
    Exp* left;
    Exp* right;
    BinaryOp op;

    BinaryExp(Exp* l, Exp* r, BinaryOp o); 
    ~BinaryExp();                          
    int accept(Visitor* visitor);
};

class NumberExp : public Exp {
public:
    int value;

    NumberExp(int v); 
    ~NumberExp();     

    int accept(Visitor* visitor);
};

class IdExp : public Exp {
public:
    string value;

    IdExp(string v); 
    ~IdExp();        

    int accept(Visitor* visitor);
};


class FcallExp : public Exp {
public:
    string nombre;
    vector<Exp*> argumentos;
    int accept(Visitor* visitor);
};


class StructAccessExp : public Exp {
public:
    string struc_id;
    string field_id;
    int accept(Visitor* visitor);
};

class ArrayAccessExp : public Exp {
public:
    string array_id;
    Exp* index;
    int accept(Visitor *visitor);
};

class StringExp : public Exp {
public:
    string value;          // contenido sin las comillas

    StringExp(string v);   // constructor
    ~StringExp();          // destructor (puede ser vacío)

    int accept(Visitor* visitor);
};

class Ternaria : public Exp {
public:
    Exp* condicion;
    Exp* then_branch;
    Exp* else_branch;
    Ternaria(){}
    ~Ternaria(){}
    int accept(Visitor *visitor);
};

class Stm : public Node {
public:
    virtual ~Stm(){}
};

class AssignStm : public Stm {
public:
    string id;
    Exp* e;
    int accept(Visitor* visitor);
};

class AssignStructStm : public Stm {
public:
    string struc_id;
    string var_id;
    Exp* e;
    int accept(Visitor* visitor);
};

class AssignArrayStm : public Stm {
public:
    string array_id;
    Exp* index;
    Exp* new_value;
    int accept(Visitor *visitor);
};

class IfStm : public Stm {
public:
    Exp* condicion;
    Body* caso1;
    Body* caso2;
    int accept(Visitor* visitor);
};

class WhileStm : public Stm {
public:
    Exp* condicion;
    Body* caso1;
    int accept(Visitor* visitor);
};

class PrintStm : public Stm {
public:
    Exp* e;
    int accept(Visitor* visitor);
};

class ReturnStm : public Stm {
public:
    Exp* e;
    int accept(Visitor* visitor);
};

class FcallStm : public Stm {
public:
    string nombre;
    vector<Exp*> argumentos;
    int accept(Visitor* visitor);
};

class Dec : public Node {
public:
    virtual ~Dec(){}
};

class VarDec : public Dec {
public:
    string tipo;
    string nombre;
    bool inner_function;
    Exp* valor;
    int accept(Visitor* visitor);
};

class ArrayDec : public Dec {
public:
    string tipo;
    string nombre;
    bool inner_function;
    Exp* size;
    vector<Exp*> valores;
    int accept(Visitor* visitor);
};


class StructDec : public Dec {
public:
    string tipo;
    string nombre;
    vector<VarDec*> declarations;
    bool inner_function;
    int accept(Visitor* visitor);
};


class FunDec : public Dec {
public:
    string tipo;
    string nombre;
    vector<string> tipos;
    vector<string> variables;
    Body* body;
    int accept(Visitor* visitor);
};

class Libreria : public Node {
public:
    string lib;
    int accept(Visitor* visitor);
};

// =====================
//      BODY
// =====================

class Body : public Node {
public:
    list<Node*> items;   // <<<<<< ESTA ES LA CLAVE
    int accept(Visitor* visitor);
};

// =====================
//      PROGRAM
// =====================

class Program : public Node {
public:
    list<Node*> items;   // <<<<<< ESTA ES LA CLAVE
    int accept(Visitor* visitor);
};

#endif
