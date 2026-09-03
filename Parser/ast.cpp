#include "ast.h"

// ------------------ BinaryExp ------------------
BinaryExp::BinaryExp(Exp* l, Exp* r, BinaryOp o)
    : left(l), right(r), op(o) {}

BinaryExp::~BinaryExp() {
    delete left;
    delete right;
}

// ------------------ NumberExp ------------------
NumberExp::NumberExp(int v) : value(v) {}

NumberExp::~NumberExp() {}

// ------------------ IdExp ------------------
IdExp::IdExp(string v) : value(v) {}

IdExp::~IdExp() {}


StringExp::StringExp(string v) : value(v) {}
StringExp::~StringExp() {}
