#include <iostream>
#include "ast.h"
#include "visitor.h"
#include <unordered_map>
using namespace std;

int Libreria::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int Program::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int FunDec::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int VarDec::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int BinaryExp::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int NumberExp::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int IdExp::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int FcallExp::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int IfStm::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int WhileStm::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int PrintStm::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int ReturnStm::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int AssignStm::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int FcallStm::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int Body::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int StructDec::accept(Visitor* visitor) {
    return visitor->visit(this);
}

int AssignStructStm::accept(Visitor *visitor) {
    return visitor->visit(this);
}

int StructAccessExp::accept(Visitor *visitor) {
    return visitor->visit(this);
}

int ArrayDec::accept(Visitor *visitor) {
    return visitor->visit(this);
}
int ArrayAccessExp::accept(Visitor *visitor) {
    return visitor->visit(this);
}
int AssignArrayStm::accept(Visitor *visitor) {
    return visitor->visit(this);
}

int StringExp::accept(Visitor *visitor) {
    return visitor->visit(this);
}

int Ternaria::accept(Visitor *visitor) {
    return visitor->visit(this);
}
///////////////////////////////////////////////////////////////



int GenCodeVisitor::generar(Program *program){
    type.type(program);
    reserva_memoria = type.fun_memoria;
    struct_campos   = type.struct_campos;

    // NUEVO
    array_sizes     = type.array_sizes;
    global_arrays   = type.global_arrays;
    fun_param_types = type.fun_param_types;
    array_params    = type.array_params;
    struct_sizes    = type.struct_sizes;
    array_dims      = type.array_dims;
    ref_params      = type.ref_params;

    out << ".data\n";
    out << "print_int_fmt: .string \"%ld \\n\"\n";
    out << "print_str_fmt: .string \"%s \\n\"\n";
    out << ".text\n";

    program->accept(this);
    return 0;
}


int GenCodeVisitor::visit(Program *program){
    out << ".data\nprint_fmt: .string \"%ld \\n\"" << endl;
    out << ".text\n";
    for (auto node : program->items) {
        node->accept(this); 
    }
    out << ".section note.GNU-stack,\"\",@progbits" << endl;
    return 0;
}

int GenCodeVisitor::visit(BinaryExp* exp) {
    exp->left->accept(this);
    out << " pushq %rax\n";
    exp->right->accept(this);
    out << " movq %rax, %rcx\n popq %rax\n";

    switch (exp->op) {
        case PLUS_OP:
            out << " addq %rcx, %rax\n";
            break;

        case MINUS_OP:
            out << " subq %rcx, %rax\n";
            break;

        case MUL_OP:
            out << " imulq %rcx, %rax\n";
            break;

        case LE_OP:   // a < b  
            out <<
                " cmpq %rcx, %rax\n"
                " movl $0, %eax\n"
                " setl %al\n"
                " movzbq %al, %rax\n";
            break;

        case GT_OP:   // a > b
            out <<
                " cmpq %rcx, %rax\n"
                " movl $0, %eax\n"
                " setg %al\n"
                " movzbq %al, %rax\n";
            break;

        case EQUAL_OP:   // a == b
            out <<
                " cmpq %rcx, %rax\n"
                " movl $0, %eax\n"
                " sete %al\n"
                " movzbq %al, %rax\n";
            break;

        case NEQUAL_OP:  // a != b
            out <<
                " cmpq %rcx, %rax\n"
                " movl $0, %eax\n"
                " setne %al\n"
                " movzbq %al, %rax\n";
            break;

    }

    return 0;
}

int GenCodeVisitor::visit(NumberExp* exp) {
    if(entornoFuncion){ 
        out << " movq $" << exp->value << ", %rax"<<endl;
    } else {
        out << exp->value << endl;
    }
    return 0;
}


int GenCodeVisitor::visit(IdExp* exp) {

    bool isRefParam =
        ref_params.count(nombreFuncion) &&
        ref_params[nombreFuncion].count(exp->value);

    if (isRefParam) {
        int off = memoria.lookup(exp->value);
        out << " movq " << off << "(%rbp), %rax\n";   
        out << " movq (%rax), %rax\n";                
    }
    else if (memoriaGlobal.count(exp->value)) {
        out << " movq " << exp->value << "(%rip), %rax\n";
    }
    else {
        out << " movq " << memoria.lookup(exp->value) << "(%rbp), %rax\n";
    }

    return 0;
}



int GenCodeVisitor::visit(PrintStm *stm) {
    std::string t = type.resolveType(stm->e);

    // Generar el valor en %rax
    stm->e->accept(this);

    // Pasar argumento a printf
    out << " movq %rax, %rsi\n";

    if (t == "string") {
        out << " leaq print_str_fmt(%rip), %rdi\n";  // "%s\n"
    } else {
        out << " leaq print_int_fmt(%rip), %rdi\n";  // "%ld\n"
    }

    out << " movl $0, %eax\n";
    out << " call printf@PLT\n";

    return 0;
}

int GenCodeVisitor::visit(AssignStm* stm) {
    // valor a asignar → %rax
    stm->e->accept(this);

    bool isRefParam =
        ref_params.count(nombreFuncion) &&
        ref_params[nombreFuncion].count(stm->id);

    if (isRefParam) {
        int off = memoria.lookup(stm->id);
        out << " movq " << off << "(%rbp), %rcx\n";  // rcx = &var real
        out << " movq %rax, (%rcx)\n";               // *(&var) = valor
    }
    else if (memoriaGlobal.count(stm->id)) {
        out << " movq %rax, " << stm->id << "(%rip)\n";
    }
    else {
        out << " movq %rax, " << memoria.lookup(stm->id) << "(%rbp)\n";
    }

    return 0;
}


int GenCodeVisitor::visit(WhileStm* stm) {
    int label = labelcont++;
    out << "while_" << label << ":"<<endl;
    stm->condicion->accept(this);
    out << " cmpq $0, %rax" << endl;
    out << " je endwhile_" << label << endl;
    stm->caso1->accept(this);
    out << " jmp while_" << label << endl;
    out << "endwhile_" << label << ":"<< endl;
    return 0;
}

int GenCodeVisitor::visit(IfStm* stm) {
    int label = labelcont++;
	int prev_offset;
    stm->condicion->accept(this);
    out << " cmpq $0, %rax"<<endl;
    out << " je else_" << label << endl;
	prev_offset = offset;
   	stm->caso1->accept(this);
    out << " jmp endif_" << label << endl;
    out << " else_" << label << ":"<< endl;
	offset = prev_offset;
    if (stm->caso2) stm->caso2->accept(this);
    out << "endif_" << label << ":"<< endl;
    return 0;
}

int GenCodeVisitor::visit(FunDec *f){
    entornoFuncion = true;
    memoria.clear();
    memoria.add_level();
    offset = -8;
    nombreFuncion = f->nombre;
    vector<std::string> argRegs = {"%rdi","%rsi","%rdx","%rcx","%r8","%r9"};
    out << ".globl " << f->nombre << endl;
    out << f->nombre << ":" << endl;
    out << " pushq %rbp" << endl;
    out << " movq %rsp, %rbp" << endl;
    out << " subq $" << reserva_memoria[f->nombre]*8 << ", %rsp" << endl;
    int size = f->variables.size();
    for(int i=0;i<size;i++){
        memoria.add_var(f->variables[i],offset);
        out << " movq " << argRegs[i] << "," << offset << "(%rbp)" << endl;
        offset -= 8;
    }

    f->body->accept(this);

    out << ".end_" << f->nombre << ":" << endl;
    out << "leave" << endl;
    out << "ret" << endl;
    entornoFuncion = false;
    memoria.remove_level();
    return 0;
}

int GenCodeVisitor::visit(VarDec *v){
    if (!entornoFuncion) {
        // ====== VARIABLES GLOBALES ======
        memoriaGlobal[v->nombre] = true;

        // ---- Caso especial: string global ----
        if (v->tipo == "string") {
            out << ".data\n";

            std::string label;

            if (auto sexp = dynamic_cast<StringExp*>(v->valor)) {
                // ¿ya existe un literal igual?
                auto it = string_labels.find(sexp->value);
                if (it == string_labels.end()) {
                    // crear nueva etiqueta
                    label = ".LC_str_" + std::to_string(string_label_count++);
                    string_labels[sexp->value] = label;

                    // emitir literal
                    out << label << ": .string \"";
                    for (char ch : sexp->value) {
                        if (ch == '\"' || ch == '\\')
                            out << "\\" << ch;
                        else
                            out << ch;
                    }
                    out << "\"\n";
                } else {
                    label = it->second;
                }
            }

            // ahora la variable global apunta al literal (o es null)
            out << v->nombre << ":\n";
            if (!label.empty()) {
                out << " .quad " << label << "\n";
            } else {
                out << " .quad 0\n";
            }

            out << ".text\n";
            return 0;
        }

        // ---- Caso general: global no-string (int, etc.) ----
        out << ".data\n";
        out << v->nombre << ":\n";

        if (v->valor != nullptr) {
            // Idealmente solo aceptamos NumberExp aquí
            if (auto num = dynamic_cast<NumberExp*>(v->valor)) {
                out << " .quad " << num->value << "\n";
            } else {
                // Si llega otra cosa rara, la dejamos en 0 para no romper ensamblador
                out << " .quad 0\n";
            }
        } else {
            out << " .quad 0\n";
        }

        out << ".text\n";
    } else {
        // ====== VARIABLES LOCALES ======

        int nSlots      = 1;          // cuántos slots de 8 bytes ocupa
        bool esStruct   = false;
        int baseOffset;               // offset donde vive la variable

        // Caso especial: variable de tipo 'struct X'
        if (v->tipo.rfind("struct ", 0) == 0) {
            esStruct = true;
            int n = 1;

            // aquí usamos el layout del struct ya copiado a struct_campos[v->nombre]
            auto it = struct_campos.find(v->nombre);
            if (it != struct_campos.end()) {
                n = static_cast<int>(it->second.size()); // nº de campos
            }

            nSlots = n;

            // Queremos que el campo 0 esté en la dirección más baja (más negativa),
            // igual que en los arrays.
            // Si offset empieza en -8 y n=3:
            // baseOffset = -8 - 8*(3-1) = -24
            // campos: 0 -> -24, 1 -> -16, 2 -> -8
            baseOffset = offset - 8 * (nSlots - 1);
        } else {
            // variables escalares normales (int, string = puntero, etc.)
            baseOffset = offset;
        }

        // Registrar variable en el Environment
        memoria.add_var(v->nombre, baseOffset);
        // Reservar espacio en el stack
        offset -= 8 * nSlots;

        // Inicialización de locales (solo escalares por ahora: int, string, ...)
        if (!esStruct && v->valor != nullptr) {
            // Evaluar expresión de inicialización → %rax
            // - Para int: NumberExp pone el entero en %rax
            // - Para string: StringExp pone la dirección del literal en %rax
            v->valor->accept(this);
            // Guardar en su slot
            out << " movq %rax, " << baseOffset << "(%rbp)\n";
        }
    }

    return 0;
}


int GenCodeVisitor::visit(Body* b) {
    memoria.add_level();           // nuevo bloque

    for (auto node : b->items) {
        node->accept(this);       
    }

    memoria.remove_level();
    return 0;
}


int GenCodeVisitor::visit(FcallExp* exp) {
    vector<string> argRegs = {"%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"};
    int size = exp->argumentos.size();

    // Tipos de parámetros de la función llamada
    vector<string> paramTypes;
    if (fun_param_types.count(exp->nombre)) {
        paramTypes = fun_param_types[exp->nombre];
    }

    for (int i = 0; i < size; i++) {
        Exp* arg = exp->argumentos[i];

        bool paramIsArray = false;
        bool paramIsRef   = false;

        if (i < (int)paramTypes.size()) {
            if (paramTypes[i].find("[]") != std::string::npos)
                paramIsArray = true;
            if (paramTypes[i].find("&") != std::string::npos)
                paramIsRef = true;
        }

        // ===== CASO: parámetro array (int[]) =====
        if (paramIsArray) {
            // (tu lógica anterior de arrays)
            if (auto id = dynamic_cast<IdExp*>(arg)) {
                std::string name = id->value;

                if (memoriaGlobal.count(name)) {
                    out << " leaq " << name << "(%rip), " << argRegs[i] << "\n";
                } else {
                    int baseOffset = memoria.lookup(name);
                    out << " leaq " << baseOffset << "(%rbp), " << argRegs[i] << "\n";
                }
                continue;
            }

            if (auto sacc = dynamic_cast<StructAccessExp*>(arg)) {
                auto itStruct = struct_campos.find(sacc->struc_id);
                if (itStruct != struct_campos.end()) {
                    auto itField = itStruct->second.find(sacc->field_id);
                    if (itField != itStruct->second.end()) {
                        int fieldIndex = itField->second;
                        int fieldDisp  = fieldIndex * 8;

                        if (memoriaGlobal.count(sacc->struc_id)) {
                            out << " leaq " << sacc->struc_id << "(%rip), "
                                << argRegs[i] << "\n";
                            if (fieldDisp != 0) {
                                out << " addq $" << fieldDisp << ", "
                                    << argRegs[i] << "\n";
                            }
                        } else {
                            int baseOffset = memoria.lookup(sacc->struc_id);
                            out << " leaq " << baseOffset << "(%rbp), "
                                << argRegs[i] << "\n";
                            if (fieldDisp != 0) {
                                out << " addq $" << fieldDisp << ", "
                                    << argRegs[i] << "\n";
                            }
                        }
                        continue;
                    }
                }
            }

            // fallback raro
            arg->accept(this);
            out << " movq %rax, " << argRegs[i] << "\n";
            continue;
        }

        // ===== CASO: parámetro por referencia int& =====
        if (paramIsRef) {
            if (auto id = dynamic_cast<IdExp*>(arg)) {
                std::string name = id->value;

                if (memoriaGlobal.count(name)) {
                    out << " leaq " << name << "(%rip), " << argRegs[i] << "\n";
                } else {
                    int off = memoria.lookup(name);
                    out << " leaq " << off << "(%rbp), " << argRegs[i] << "\n";
                }
            } else {
                // Si no es lvalue simple, caemos a pasar por valor
                arg->accept(this);
                out << " movq %rax, " << argRegs[i] << "\n";
            }
            continue;
        }

        // ===== CASO: parámetro normal (int por valor) =====
        // Mantenemos tu caso especial de "si es array, pasar puntero"
        if (auto id = dynamic_cast<IdExp*>(arg)) {
            std::string name = id->value;
            if (array_sizes.count(name)) {
                if (memoriaGlobal.count(name)) {
                    out << " leaq " << name << "(%rip), " << argRegs[i] << "\n";
                } else {
                    int baseOffset = memoria.lookup(name);
                    out << " leaq " << baseOffset << "(%rbp), " << argRegs[i] << "\n";
                }
                continue;
            }
        }

        // Caso general
        arg->accept(this);
        out << " movq %rax, " << argRegs[i] << "\n";
    }

    out << "call " << exp->nombre << "\n";
    return 0;
}




int GenCodeVisitor::visit(ReturnStm *stm){
    stm->e->accept(this);
    out << " jmp .end_" << nombreFuncion << endl;
    return 0;
}


int GenCodeVisitor::visit(FcallStm* stm) {
    vector<std::string> argRegs = {"%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"};
    int size = stm->argumentos.size();

    // Tipos de parámetros de la función llamada
    std::vector<std::string> paramTypes;
    if (fun_param_types.count(stm->nombre)) {
        paramTypes = fun_param_types[stm->nombre];
    }

    for (int i = 0; i < size; ++i) {
        Exp* arg = stm->argumentos[i];

        bool paramIsArray = false;
        bool paramIsRef   = false;

        if (i < (int)paramTypes.size()) {
            if (paramTypes[i].find("[]") != std::string::npos)
                paramIsArray = true;
            if (paramTypes[i].find("&") != std::string::npos)
                paramIsRef = true;
        }

        // ===== array =====
        if (paramIsArray) {
            if (auto id = dynamic_cast<IdExp*>(arg)) {
                std::string name = id->value;
                if (memoriaGlobal.count(name)) {
                    out << " leaq " << name << "(%rip), " << argRegs[i] << "\n";
                } else {
                    int baseOffset = memoria.lookup(name);
                    out << " leaq " << baseOffset << "(%rbp), " << argRegs[i] << "\n";
                }
                continue;
            }
            // (si quieres, añade lo de struct.grades aquí igual que en FcallExp)

            arg->accept(this);
            out << " movq %rax, " << argRegs[i] << "\n";
            continue;
        }

        // ===== referencia int& =====
        if (paramIsRef) {
            if (auto id = dynamic_cast<IdExp*>(arg)) {
                std::string name = id->value;
                if (memoriaGlobal.count(name)) {
                    out << " leaq " << name << "(%rip), " << argRegs[i] << "\n";
                } else {
                    int off = memoria.lookup(name);
                    out << " leaq " << off << "(%rbp), " << argRegs[i] << "\n";
                }
            } else {
                arg->accept(this);
                out << " movq %rax, " << argRegs[i] << "\n";
            }
            continue;
        }

        // ===== normal =====
        if (auto id = dynamic_cast<IdExp*>(arg)) {
            std::string name = id->value;
            if (array_sizes.count(name)) {
                if (memoriaGlobal.count(name)) {
                    out << " leaq " << name << "(%rip), " << argRegs[i] << "\n";
                } else {
                    int baseOffset = memoria.lookup(name);
                    out << " leaq " << baseOffset << "(%rbp), " << argRegs[i] << "\n";
                }
                continue;
            }
        }

        arg->accept(this);
        out << " movq %rax, " << argRegs[i] << "\n";
    }

    out << "call " << stm->nombre << "\n";
    return 0;
}

int GenCodeVisitor::visit(Libreria *lib){
    return 0;
}

int GenCodeVisitor::visit(StructDec *dec){
    int numCampos = dec->declarations.size();
    int bytes = 8 * numCampos;  // 8 bytes por campo

    if (dec->inner_function) {
        // ===== struct local =====
        int baseOffset = offset;            // p.ej. -8
        memoria.add_var(dec->nombre, baseOffset);
        offset -= bytes;                    // reservamos N slots: -8, -16, ... luego queda -24
    } else {
        // ===== struct global =====
        memoriaGlobal[dec->nombre] = true;
        out << ".data\n";
        out << dec->nombre << ":\n";
        out << " .zero " << bytes << "\n";
        out << ".text\n";
    }
    return 0;
}


int GenCodeVisitor::visit(AssignStructStm *stm){
    // 1. Evaluar la expresión del lado derecho
    stm->e->accept(this);  // deja el valor en %rax

    // 2. Buscar el struct y el campo
    auto itStruct = struct_campos.find(stm->struc_id);
    if (itStruct == struct_campos.end()) {
        // No conocemos ese struct, podrías lanzar error o ignorar
        // throw runtime_error("Struct no declarado: " + stm->struc_id);
        return 0;
    }

    auto itField = itStruct->second.find(stm->var_id);
    if (itField == itStruct->second.end()) {
        // Campo no encontrado
        // throw runtime_error("Campo no encontrado en struct: " + stm->var_id);
        return 0;
    }

    int index = itField->second;   // índice del campo (0,1,2,...)
    int disp  = index * 8;         // offset en bytes (asumiendo 8 bytes por campo)

    // 3. ¿Struct global o local?
    if (memoriaGlobal.count(stm->struc_id)) {
        // ===== struct global =====
        if (disp == 0) {
            out << " movq %rax, " << stm->struc_id << "(%rip)\n";
        } else {
            out << " movq %rax, " << stm->struc_id << "+" << disp << "(%rip)\n";
        }
    } else {
        // ===== struct local en el stack =====
        int baseOffset = memoria.lookup(stm->struc_id); // offset base del struct
        int totalOffset = baseOffset + disp; //antes era
        out << " movq %rax, " << totalOffset << "(%rbp)\n";
    }

    return 0;
}

int GenCodeVisitor::visit(StructAccessExp *exp){
    auto itStruct = struct_campos.find(exp->struc_id);
    if (itStruct == struct_campos.end()) {
        // struct no encontrado
        return 0;
    }

    auto itField = itStruct->second.find(exp->field_id);
    if (itField == itStruct->second.end()) {
        // campo no encontrado
        return 0;
    }

    int index = itField->second;   // 0, 1, 2, ...
    int disp  = index * 8;         // offset en bytes

    if (memoriaGlobal.count(exp->struc_id)) {
        // struct global
        if (disp == 0) {
            out << " movq " << exp->struc_id << "(%rip), %rax\n";
        } else {
            out << " movq " << exp->struc_id << "+" << disp << "(%rip), %rax\n";
        }
    } else {
        // struct local
        int baseOffset = memoria.lookup(exp->struc_id);
        int totalOffset = baseOffset + disp;
        out << " movq " << totalOffset << "(%rbp), %rax\n";
    }

    return 0;
}


int GenCodeVisitor::visit(ArrayDec *dec){
    // tamaño
    int n = 1;
    auto it = array_sizes.find(dec->nombre);
    if (it != array_sizes.end()) {
        n = it->second;
    } else if (auto num = dynamic_cast<NumberExp*>(dec->size)) {
        n = num->value;
    }

    if (!dec->inner_function) {
        // ====== ARRAY GLOBAL ======
        memoriaGlobal[dec->nombre] = true;
        out << ".data\n";
        out << dec->nombre << ":\n";

        if (!dec->valores.empty()) {
            int k = dec->valores.size();
            // inicializadores explícitos
            for (int i = 0; i < k; ++i) {
                if (auto num = dynamic_cast<NumberExp*>(dec->valores[i])) {
                    out << " .quad " << num->value << "\n";
                } else {
                    // si quisieras soportar expresiones más generales, tendrías que evaluarlas antes
                    out << " .quad 0\n";
                }
            }
            // rellenar el resto con 0
            for (int i = k; i < n; ++i) {
                out << " .quad 0\n";
            }
        } else {
            // sin inicialización: todo a 0
            out << " .zero " << (n * 8) << "\n";
        }

        out << ".text\n";
    } else {
        // ====== ARRAY LOCAL ======
        // Queremos que el elemento 0 esté en la dirección más baja (más negativa)
        // y los siguientes hacia arriba. Como usamos base + index*8, la base debe ser
        // la más negativa.

        int baseOffset = offset - 8 * (n - 1);  // ej: offset=-8, n=3 → base=-24
        memoria.add_var(dec->nombre, baseOffset);

        // consumimos n slots
        offset -= 8 * n;    // ej: -8 -24 = -32

        // inicialización { ... } si existe
        if (!dec->valores.empty()) {
            int k = dec->valores.size();
            for (int i = 0; i < k && i < n; ++i) {
                dec->valores[i]->accept(this);   // valor en %rax
                int elemOffset = baseOffset + 8 * i;
                out << " movq %rax, " << elemOffset << "(%rbp)\n";
            }
            // resto de elementos no inicializados explícitamente → 0 si quieres:
            for (int i = k; i < n; ++i) {
                int elemOffset = baseOffset + 8 * i;
                out << " movq $0, " << elemOffset << "(%rbp)\n";
            }
        }
        // si no hay initializer list, puedes dejarlos basura o inicializar a 0 tú
    }

    return 0;
}


int GenCodeVisitor::visit(ArrayAccessExp *exp){
    // Evaluar índice → %rax
    exp->index->accept(this);
    out << " movq %rax, %rcx\n";   // index
    out << " imulq $8, %rcx\n";    // index * 8

    bool isParamArray =
        array_params.count(nombreFuncion) &&
        array_params[nombreFuncion].count(exp->array_id);

    if (isParamArray) {
        // scores es parámetro array: el slot guarda un puntero
        int slotOff = memoria.lookup(exp->array_id);
        out << " movq " << slotOff << "(%rbp), %rax\n";  // %rax = base pointer
    } else if (memoriaGlobal.count(exp->array_id)) {
        // array global
        out << " leaq " << exp->array_id << "(%rip), %rax\n";
    } else {
        // array local
        int baseOff = memoria.lookup(exp->array_id);
        out << " leaq " << baseOff << "(%rbp), %rax\n";
    }

    out << " addq %rcx, %rax\n";    // base + index*8
    out << " movq (%rax), %rax\n";  // carga arr[i] → %rax
    return 0;
}

int GenCodeVisitor::visit(AssignArrayStm *stm){
    // new_value → %rax
    stm->new_value->accept(this);
    out << " pushq %rax\n";        // guardar valor

    // index → %rax
    stm->index->accept(this);
    out << " movq %rax, %rcx\n";   // index
    out << " imulq $8, %rcx\n";    // index*8

    bool isParamArray =
        array_params.count(nombreFuncion) &&
        array_params[nombreFuncion].count(stm->array_id);

    if (isParamArray) {
        int slotOff = memoria.lookup(stm->array_id);
        out << " movq " << slotOff << "(%rbp), %rax\n";  // %rax = base pointer
    } else if (memoriaGlobal.count(stm->array_id)) {
        out << " leaq " << stm->array_id << "(%rip), %rax\n";
    } else {
        int baseOff = memoria.lookup(stm->array_id);
        out << " leaq " << baseOff << "(%rbp), %rax\n";
    }

    out << " addq %rcx, %rax\n";   // dirección de arr[i]
    out << " popq %rcx\n";         // valor
    out << " movq %rcx, (%rax)\n"; // arr[i] = valor
    return 0;
}

int GenCodeVisitor::visit(StringExp *exp) {
    // ¿ya tenemos una etiqueta para este literal?
    auto it = string_labels.find(exp->value);
    std::string label;
    if (it == string_labels.end()) {
        // crear nueva etiqueta
        label = ".LC_str_" + std::to_string(string_label_count++);
        string_labels[exp->value] = label;

        // Emitimos el literal en .data
        out << ".data\n";
        out << label << ": .string \"";

        // OJO: aquí asumimos que exp->value no trae comillas ni escapes raros
        // Si tu scanner deja caracteres tal cual, esto funciona simple.
        for (char ch : exp->value) {
            if (ch == '\"' || ch == '\\') {
                out << "\\" << ch; // escapamos " y 
            } else {
                out << ch;
            }
        }
        out << "\"\n";
        out << ".text\n";
    } else {
        label = it->second;
    }

    // Devolvemos en %rax la dirección del string
    out << " leaq " << label << "(%rip), %rax\n";
    return 0;
}


int GenCodeVisitor::visit(Ternaria *exp) {
    int label = labelcont++;

    // cond → %rax
    exp->condicion->accept(this);
    out << " cmpq $0, %rax\n";
    out << " je tern_else_" << label << "\n";

    // then_branch
    exp->then_branch->accept(this);  // deja resultado en %rax
    out << " jmp tern_end_" << label << "\n";

    // else_branch
    out << "tern_else_" << label << ":\n";
    exp->else_branch->accept(this);  // deja resultado en %rax

    out << "tern_end_" << label << ":\n";

    // El valor final de la expresión queda en %rax
    return 0;
}


/////////////////////////////////////////////


int TypeCheckerVisitor::type(Program *program){
    locales = 0;
    program->accept(this);
    return 0;
}

int TypeCheckerVisitor::visit(Program *program){
    // Recorremos todos los nodos del toplevel
    for (auto node : program->items) {
        node->accept(this);
    }
    return 0;
}


int TypeCheckerVisitor::visit(BinaryExp *exp){
    return 0;
}

int TypeCheckerVisitor::visit(NumberExp *exp){
    return 0;
}

int TypeCheckerVisitor::visit(IdExp *exp){
    return 0;
}

int TypeCheckerVisitor::visit(PrintStm *stm){
    return 0;
}

int TypeCheckerVisitor::visit(AssignStm *stm){
    return 0;
}

int TypeCheckerVisitor::visit(WhileStm *stm){
    stm->caso1->accept(this);
    return 0;
}

int TypeCheckerVisitor::visit(IfStm* stm) {
    int a = locales;
    stm->caso1->accept(this);
    int b = locales;
    stm->caso2->accept(this);
    int c = locales;
    locales = a + max(b-a,c-b);
    return 0;
}


int TypeCheckerVisitor::visit(FunDec *f){
    int parametros = f->tipos.size();

    // Guardar tipos de parámetros por función
    fun_param_types[f->nombre] = f->tipos;

    // Marcar cuáles parámetros son arrays (tipo "int[]", por ejemplo)
    for (int i = 0; i < parametros; ++i) {
        const std::string &t = f->tipos[i];
        const std::string &v = f->variables[i];
        if (t.find("[]") != std::string::npos) {
            array_params[f->nombre].insert(v);
        }
       if (t.find("&") != std::string::npos) {
            ref_params[f->nombre].insert(v);
        }
    }

    locales = 0;
    f->body->accept(this);
    fun_memoria[f->nombre] = parametros + locales;
    return 0;
}


int TypeCheckerVisitor::visit(VarDec *v){
    int slots = 1; // por defecto, 1 slot de 8 bytes

    // 1) Registrar tipo de variable según sea global o local
    if (!v->inner_function) {
        // variable global
        global_var_types[v->nombre] = v->tipo;
    } else {
        // variable local
        local_var_types[v->nombre] = v->tipo;
    }

    // 2) ¿Es variable de tipo 'struct X'?
    if (v->tipo.rfind("struct ", 0) == 0) {  // empieza por "struct "
        std::string structName = v->tipo.substr(7); // salta "struct "
        if (!structName.empty() && structName[0] == ' ')
            structName.erase(0, 1);

        auto it = struct_campos.find(structName);
        if (it != struct_campos.end()) {
            // Copiamos el layout del tipo 'structName' a la variable concreta 'v->nombre'
            struct_campos[v->nombre] = it->second;

            // Número de campos = número de slots que ocupa este struct
            slots = static_cast<int>(it->second.size());
        }
    }

    // 3) Sumamos los slots que realmente ocupa esta variable
    locales += slots;
    return 0;
}


int TypeCheckerVisitor::visit(Body *body){
    for (auto node : body->items) {
        node->accept(this);
    }
    return 0;
}

int TypeCheckerVisitor::visit(FcallExp *exp){
    return 0;
}

int TypeCheckerVisitor::visit(ReturnStm *stm){
    return 0;
}

int TypeCheckerVisitor::visit(FcallStm *stm){
    return 0;
}

int TypeCheckerVisitor::visit(Libreria *lib){
    return 0;
}

int TypeCheckerVisitor::visit(StructDec *dec){
    // Calcular offsets de los campos, en unidades de "slots"
    int index = 0;
    for (auto campo : dec->declarations) {
        struct_campos[dec->nombre][campo->nombre] = index;
        index++;
    }

    if (dec->inner_function) {
        // cada campo cuenta como un local (8 bytes)
        locales += dec->declarations.size();
    }
    return 0;
}


int TypeCheckerVisitor::visit(AssignStructStm *dec){
    return 0;
}

int TypeCheckerVisitor::visit(StructAccessExp *exp) {

    return 0;
}


int TypeCheckerVisitor::visit(ArrayDec *dec){
    // Asumimos que size es una constante numérica tipo NumberExp
    int n = 1;
    if (auto num = dynamic_cast<NumberExp*>(dec->size)) {
        n = num->value;
    }
    array_sizes[dec->nombre] = n;

    if (!dec->inner_function) {
        // array global: no afecta locales
        global_arrays.insert(dec->nombre);
    } else {
        // array local: ocupa 'n' slots de 8 bytes
        locales += n;
    }
    return 0;
}


int TypeCheckerVisitor::visit(ArrayAccessExp *exp){
    return 0;
}

int TypeCheckerVisitor::visit(AssignArrayStm *stm){
    return 0;
}



int TypeCheckerVisitor::visit(StringExp *exp){
    return 0;
}

int TypeCheckerVisitor::visit(Ternaria *exp) {
    // Forzamos a visitar las subexpresiones por si en el futuro
    // acumulas info/contexto
    if (exp->condicion)  exp->condicion->accept(this);
    if (exp->then_branch)  exp->then_branch->accept(this);
    if (exp->else_branch)  exp->else_branch->accept(this);

    // Chequeos ligeros de tipo (opcional pero útil):
    std::string tCond = resolveType(exp->condicion);
    if (tCond != "int") {
        std::cerr << "[Advertencia] Condición de operador ternario no es int\n";
    }

    std::string tThen = resolveType(exp->then_branch);
    std::string tElse = resolveType(exp->else_branch);
    if (tThen != tElse) {
        std::cerr << "[Advertencia] Ramos del ternario tienen tipos distintos: "
                  << tThen << " y " << tElse << "\n";
    }

    // No modifica locales, así que solo retornamos 0
    return 0;
}



// helper: lookup de tipo de variable
string TypeCheckerVisitor::getVarType(const string &name) {
    if (local_var_types.count(name))  return local_var_types.at(name);
    if (global_var_types.count(name)) return global_var_types.at(name);
    return "int";   // por defecto, si no la conocemos
}

// helper: tipo de una expresión
string TypeCheckerVisitor::resolveType(Exp *e) {
    if (auto num = dynamic_cast<NumberExp*>(e)) {
        return "int";
    }
    if (auto str = dynamic_cast<StringExp*>(e)) {
        return "string";
    }
    if (auto id = dynamic_cast<IdExp*>(e)) {
        return getVarType(id->value);
    }
    if (auto bin = dynamic_cast<BinaryExp*>(e)) {
        // Por ahora asumimos operaciones numéricas
        return "int";
    }
    if (auto aacc = dynamic_cast<ArrayAccessExp*>(e)) {
        // por ahora arrays de enteros
        return "int";
    }
    if (auto sacc = dynamic_cast<StructAccessExp*>(e)) {
        // tus structs por ahora solo tienen ints / arrays de ints
        return "int";
    }

    if (auto fce = dynamic_cast<FcallExp*>(e)) {
        // si quieres, podrías usar fun_param_types para ver tipos de retorno
        // De momento asumimos que todas las funciones devuelven int
        return "int";
    }
    if (auto ter = dynamic_cast<Ternaria*>(e)) {
        std::string tThen = resolveType(ter->then_branch);
        std::string tElse = resolveType(ter->else_branch);
        if (tThen == tElse) {
            return tThen;
        }
        // Si difieren, por ahora devolvemos int por defecto
        // o podrías lanzar error semántico si quieres.
        return "int";
    }


    // fallback
    return "int";
}
