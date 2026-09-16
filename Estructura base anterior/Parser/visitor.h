#ifndef VISITOR_H
#define VISITOR_H
#include "ast.h"
#include <list>
#include <vector>
#include <unordered_map>
#include <unordered_set>

#include <string>
#include "environment.h"
using namespace std;


class Visitor {
public:
    virtual int visit(Program *p) = 0;
    virtual int visit(BinaryExp *exp) = 0;
    virtual int visit(NumberExp *exp) = 0;
    virtual int visit(IdExp *exp) = 0;
    virtual int visit(PrintStm *stm) = 0;
    virtual int visit(AssignStm *stm) = 0;
    virtual int visit(WhileStm *stm) = 0;
    virtual int visit(IfStm *stm) = 0;
    virtual int visit(FunDec  *f) = 0;
    virtual int visit(VarDec *v) = 0;
    virtual int visit(Body *body) = 0;
    virtual int visit(FcallExp *exp) = 0;
    virtual int visit(ReturnStm *stm) = 0;
    virtual int visit(FcallStm *stm) = 0;
    virtual int visit(Libreria *lib) = 0;
    virtual int visit(StructDec *dec) = 0;
    virtual int visit(AssignStructStm *stm) = 0;
    virtual int visit(StructAccessExp *exp) = 0;
    virtual int visit(ArrayDec *exp) = 0;
    virtual int visit(ArrayAccessExp *exp) = 0;
    virtual int visit(AssignArrayStm *stm) = 0;
    virtual int visit(StringExp* exp) = 0;
    virtual int visit(Ternaria* exp) = 0;

};


class TypeCheckerVisitor : public Visitor {
public:
    unordered_map<string,int> fun_memoria;
    unordered_map<string, unordered_map<string,int>> struct_campos;
    unordered_map<string, int> array_sizes;
    unordered_set<string> global_arrays;
    unordered_map<string, vector<string>> fun_param_types;
    unordered_map<string, unordered_set<string>> array_params;
    std::unordered_map<std::string,int> struct_sizes;
    unordered_map<string,string> global_var_types;  
    unordered_map<string,string> local_var_types;   
    unordered_map<string, vector<int>> array_dims;
    std::unordered_map<std::string, std::unordered_set<std::string>> ref_params;

    bool inFunction = false;
    int locales;
    int type(Program *program);
    int visit(Program *p) override;
    int visit(BinaryExp *exp) override;
    int visit(NumberExp *exp) override;
    int visit(IdExp *exp) override;
    int visit(PrintStm *stm) override;
    int visit(AssignStm *stm) override;
    int visit(WhileStm *stm) override;
    int visit(IfStm *stm) override;
    int visit(FunDec *f) override;
    int visit(VarDec *v) override;
    int visit(Body *body) override;
    int visit(FcallExp *exp) override;
    int visit(ReturnStm *stm) override;
    int visit(FcallStm *stm) override;
    int visit(Libreria *lib) override;
    int visit(StructDec *dec) override;
    int visit(AssignStructStm *stm) override;
    int visit(StructAccessExp *exp) override;
    int visit(ArrayDec *exp) override;
    int visit(ArrayAccessExp *exp) override;
    int visit(AssignArrayStm *stm) override;
    int visit(StringExp* exp) override;
    int visit(Ternaria* exp) override;
    string resolveType(Exp *e);
    string getVarType(const string &name);
};

class GenCodeVisitor : public Visitor {
private:
    std::ostream& out;
public:
    TypeCheckerVisitor type;
    unordered_map<string,int> reserva_memoria;
    GenCodeVisitor(std::ostream& out) : out(out) {}
    int generar(Program *program);
    Environment<int> memoria;
    unordered_map<string,bool> memoriaGlobal;
    unordered_map<string, unordered_map<string,int>> struct_campos;
    std::unordered_map<std::string, int> array_sizes;
    std::unordered_set<std::string> global_arrays;
    std::unordered_map<std::string, std::vector<std::string>> fun_param_types;
    std::unordered_map<std::string, std::unordered_set<std::string>> array_params;\
    std::unordered_map<std::string,int> struct_sizes;
    unordered_map<string,string> global_var_types;  // tipo de variables globales
    unordered_map<string,string> local_var_types;   // tipo de variables locales
    unordered_map<string, vector<int>> array_dims;
    std::unordered_map<std::string,std::string> string_labels;
    std::unordered_map<std::string, std::unordered_set<std::string>> ref_params;
    // void emitStructFieldAddress(StructAccessExp* sae,const std::string& destReg);
    int offset = -8;
    int labelcont = 0;
    bool entornoFuncion = false;
    int string_label_count = 0;
    string nombreFuncion;
    int visit(Program *p) override;
    int visit(BinaryExp *exp) override;
    int visit(NumberExp *exp) override;
    int visit(IdExp *exp) override;
    int visit(PrintStm *stm) override;
    int visit(AssignStm *stm) override;
    int visit(WhileStm *stm) override;
    int visit(IfStm *stm) override;
    int visit(FunDec *f) override;
    int visit(VarDec *v) override;
    int visit(Body *body) override;
    int visit(FcallExp *exp) override;
    int visit(ReturnStm *stm) override;
    int visit(FcallStm *stm) override;
    int visit(Libreria *lib) override;  
    int visit(StructDec *dec) override;
    int visit(AssignStructStm *stm) override;
    int visit(StructAccessExp *exp) override;
    int visit(ArrayDec *exp) override;
    int visit(ArrayAccessExp *exp) override;
    int visit(AssignArrayStm *stm) override;
    int visit(StringExp* exp) override;
    int visit(Ternaria* exp) override;

};

#endif // VISITOR_H