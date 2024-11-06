from __future__ import annotations
import dataclasses
import enum
from typing import *
from lsra import RegSpill, RegRestore

class Operator(enum.Enum):
    Add = enum.auto()
    Sub = enum.auto()
    Mul = enum.auto()
    Div = enum.auto()

    Eq = enum.auto()

class TreeKind(enum.Enum):
    LdLocal = enum.auto()
    StLocal = enum.auto()
    Const = enum.auto()
    Discard = enum.auto()
    BinOp = enum.auto()

    # Reserved for terminals
    Ret = enum.auto()
    Branch = enum.auto()
    Jmp = enum.auto()

@dataclasses.dataclass
class Tree:
    kind: TreeKind
    subtrees: list[Tree]
    operands: list
    parent: Tree | None

    # Assigned during Ir.reindex()
    ir_idx: int = 0
    # Assigned during Lsra.do_linear_scan
    reg: int = -1
    spills: list[RegSpill] = dataclasses.field(default_factory=list)
    restores: list[RegRestore] = dataclasses.field(default_factory=list)
    
    def tree_execution_order(self) -> Iterable[Tree]:
        for subtree in self.subtrees:
            for tree in subtree.tree_execution_order():
                yield tree
        
        yield self

    def dump(self, indent_level: int = 0):
        for tree in self.subtrees:
            tree.dump(indent_level + 4)

        for spill in self.spills:
            print(" " * indent_level + str(spill))
        for restore in self.restores:
            print(" " * indent_level + str(restore))
        reg = "" if self.parent == None else "(r" + str(self.reg) + ") "
        print(
            " " * indent_level +
            "[" + str(self.ir_idx) + "] " +
            reg +
            self.kind.name +
            "(" + ", ".join(map(str, self.operands)) + ")"
        )

@dataclasses.dataclass
class Statement:
    il_idx: int
    next_statement: Statement | None
    prev_statement: Statement | None
    tree: Tree

@dataclasses.dataclass
class BasicBlock:
    il_idx: int
    next_block: BasicBlock | None
    prev_block: BasicBlock | None
    first_statemenent: Statement | None
    last_statement: Statement | None

    predecessors: list[BasicBlock] = dataclasses.field(default_factory=list)

    def tree_execution_order(self) -> Iterable[Tree]:
        statement = self.first_statemenent
        while statement != None:
            for t in statement.tree.tree_execution_order():
                yield t
            statement = statement.next_statement

    def append_tree(self, il_idx: int, tree: Tree) -> None:
        new_statement = Statement(il_idx=il_idx, tree=tree, next_statement=None, prev_statement=self.last_statement)
        if (self.last_statement == None):
            self.last_statement = new_statement
            self.first_statemenent = new_statement
            return
        self.last_statement.next_statement = new_statement
        self.last_statement = new_statement
    
    def __str__(self) -> str:
        return f"blk 0x{hex(self.il_idx)[2:].zfill(4)}"

class BasicBlockList:
    first: BasicBlock
    
    def __init__(self) -> None:
        self.first = BasicBlock(il_idx=0, next_block=None, prev_block=None, first_statemenent=None, last_statement=None)

    def get_or_insert_block_at(self, il_idx: int) -> BasicBlock:
        block = self.first
        while block.il_idx < il_idx:
            if block.next_block == None or block.next_block.il_idx > il_idx:
                break
            block = block.next_block
        
        if block.il_idx == il_idx:
            return block
        
        statement = block.first_statemenent
        while statement.il_idx < il_idx:
            if statement.next_statement == None:
                # il_idx lands past the block

                # insert a new block into the doubly linked list
                new_block = BasicBlock(il_idx=il_idx, next_block=block.next_block, prev_block=block.prev_block, first_statemenent=None, last_statement=None)
                block.next_block = new_block
                if (new_block.next_block != None):
                    new_block.next_block.prev_block = new_block

                return new_block
            statement = statement.next_statement
        
        if statement.il_idx > il_idx:
            # il_idx lands between two statements
            print("panic : il_idx lands between two statements")
            exit(1)
        
        # insert a new block into the doubly linked list
        new_block = BasicBlock(il_idx=il_idx, next_block=block.next_block, prev_block=block.prev_block, first_statemenent=None, last_statement=None)
        block.next_block = new_block
        if (new_block.next_block != None):
            new_block.next_block.prev_block = new_block
        
        new_block.first_statemenent = statement
        new_block.last_statement = block.last_statement

        jmp_statement = Statement(il_idx=0, next_statement=None, prev_statement=block.last_statement.prev_statement, tree=Tree(
            kind=TreeKind.Jmp,
            subtrees=[],
            operands=[new_block],
            parent=None
        ))
        if (jmp_statement.prev_statement != None):
            jmp_statement.prev_statement.next_statement = jmp_statement
            jmp_statement.il_idx = jmp_statement.prev_statement.il_idx
        else:
            jmp_statement.il_idx = block.il_idx
        if (block.last_statement is block.first_statemenent):
            block.first_statemenent = jmp_statement
        block.last_statement = jmp_statement
        new_block.first_statemenent.prev_statement = None

        return new_block

@dataclasses.dataclass
class Ir:
    blocks: BasicBlockList
    local_vars: int

    ir_idx_count: int = 0

    def recompute_predecessors(self) -> None:
        block = self.blocks.first
        while block != None:
            for operand in block.last_statement.tree.operands:
                operand.predecessors.append(block)
            block = block.next_block

    def reindex(self) -> None:
        index = 0

        for tree in self.tree_execution_order():
            tree.ir_idx = index
            index += 1
        
        self.ir_idx_count = index
    
    def block_execution_order(self) -> Iterable[BasicBlock]:
        block = self.blocks.first
        while block != None:
            yield block
            block = block.next_block
    
    def tree_execution_order(self) -> Iterable[Tree]:
        block = self.blocks.first
        while block != None:
            statement = block.first_statemenent
            while statement != None:
                for t in statement.tree.tree_execution_order():
                    yield t
                statement = statement.next_statement
            block = block.next_block

    def dump(self) -> None:
        block = self.blocks.first
        while block != None:
            print(f"blk 0x{hex(block.il_idx)[2:].zfill(4)} - predecessors: [" + ", ".join(str(pred) for pred in block.predecessors) + "]")
            statement = block.first_statemenent
            while statement != None:
                print(f"stmt 0x{hex(statement.il_idx)[2:].zfill(4)}")
                statement.tree.dump()
                statement = statement.next_statement
            block = block.next_block