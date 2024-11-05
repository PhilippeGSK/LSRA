from __future__ import annotations
import dataclasses
from ir import *
import ir as irepr

@dataclasses.dataclass
class Register:
    active_interval: Interval | None

@dataclasses.dataclass
class RegSpill:
    reg: int
    interval: Interval

    def __str__(self) -> str:
        return f"spill {self.interval} from r{self.reg}"

@dataclasses.dataclass
class RegRestore:
    reg: int
    interval: Interval
    
    def __str__(self) -> str:
        return f"restore {self.interval} into r{self.reg}"

@dataclasses.dataclass
class LiveRange:
    first_write_at: int
    last_read_at: int

@dataclasses.dataclass
class UsePos:
    belongs_to: Interval
    used_in: Tree

@dataclasses.dataclass
class Interval:
    of: int | Tree
    use_positions: list[UsePos]
    live_range: LiveRange
    live_in: int | None

    def __str__(self):
        if isinstance(self.of, int):
            return f"local {self.of}"
        else:
            return f"tree tmp {self.of.ir_idx}"
        
    def first_use_pos(self, current_pos: int) -> UsePos | None:
        for use_pos in self.use_positions:
            if use_pos.used_in.ir_idx < current_pos:
                continue

            return use_pos
        
        return None

class Lsra:
    registers: list[Register]
    var_intervals: list[Interval]
    tree_intervals: list[Interval]
    active_intervals: list[Interval]
    current_tree: Tree
    
    # Whether or not we ourselves to free the intervals that are about to be read so that we can reuse the registers for operands
    # and output
    # Also see related comment on try_allocate_with_free_reg
    allow_operand_reuse: bool

    def __init__(self, num_regs: int = 4, allow_operand_reuse: bool = True) -> None:
        self.registers = []
        for _ in range(num_regs):
            self.registers.append(Register(active_interval=None))
        self.allow_operand_reuse = allow_operand_reuse
        self.var_intervals = []
        self.tree_intervals = []
        self.active_intervals = []
        self.current_tree = None
    
    # Removes expired intervals from the active_intervals list and frees the corresponding registers
    def free_intervals(self) -> None:
        pos = self.current_tree.ir_idx
        new_active_intervals = []
        for active_interval in self.active_intervals:
            if active_interval.live_range.last_read_at > pos:
                new_active_intervals.append(active_interval)
            # If we allow operand reuse, we free operand registers for the output
            elif not self.allow_operand_reuse and active_interval.live_range.last_read_at == pos:
                new_active_intervals.append(active_interval)
            else:
                reg: Register = self.registers[active_interval.live_in]
                reg.active_interval = None
                active_interval.live_in = None
        self.active_intervals = new_active_intervals
    
    # Tries to make an interval active without spilling
    # If possible, we'd like to reuse the register of one of the operands (only useful when we have allow_operand_reuse)
    # The reason is because we'd rather emit, in the future, the following :
    # `add r2, r1`
    # which reuses r2 as both the operand and result register
    # instead of the following
    # `mov r0, r2`
    # `add r2, r1`
    # just because r0 was free
    def try_activate_with_free_reg(self, inter: Interval) -> bool:
        best_reg_i = -1
        best_reg: Register | None = None

        for reg_i, reg in enumerate(self.registers):
            if reg.active_interval == None:
                if best_reg == None:
                    best_reg = reg
                    best_reg_i = reg_i
                else:
                    # Check if the reg is already one of the operands. If yes, that'll be the best reg we can find
                    done_searching = False
                    for subtree in inter.first_use_pos(self.current_tree.ir_idx).used_in.subtrees:
                        if subtree.reg == reg_i:
                            best_reg = reg
                            best_reg_i = best_reg_i
                            done_searching = True
                            break
                    if done_searching:
                        break

        if best_reg == None:
            return False

        # If the current tree isn't the one that writes the value or if it doesn't already restore the value, 
        # we need to add a restore. This is only applicable to the first load of a variable
        if self.current_tree is not inter.of:
            if not any(restore.interval == inter for restore in self.current_tree.restores):
                self.current_tree.restores.append(RegRestore(reg=best_reg_i, interval=inter))
        best_reg.active_interval = inter
        inter.live_in = best_reg_i
        self.active_intervals.append(inter)
        return True
    
    # Ensures an interval is active
    def activate_interval(self, inter: Interval) -> None:
        if (inter.live_in != None):
            # Interval is already active
            return
        
        # If we can, we should use a free register
        if (self.try_activate_with_free_reg(inter)):
            return
        
        # We couldn't find a free register, we need to spill one

        # Find the best candiate to spill
        # The heuristic used here is to pick the one which will have to be restored the furthest in the future
        current_pos = self.current_tree.ir_idx
        inter_use_pos = inter.first_use_pos(current_pos)    
        # This shouldn't happen because we shouldn't activate intervals that aren't going to be used anymore
        assert inter_use_pos != None
        best_interval: Interval | None = None
        best_use_pos: UsePos | None = None
        for active_interval in self.active_intervals:
            use_pos = active_interval.first_use_pos(current_pos)
            # This shouldn't happen because active intervals should have use positions in the future
            # We called free_intervals() to ensure that
            assert use_pos != None, "None use pos"
            
            # We can't spill an interval we're about to use
            if use_pos.used_in.ir_idx <= inter_use_pos.used_in.ir_idx:
                continue

            if best_use_pos == None or use_pos.used_in.ir_idx > best_use_pos.used_in.ir_idx:
                best_interval = active_interval
                best_use_pos = use_pos

        if best_interval == None:
            print ("regs")
            for reg in self.registers:
                print("    " + str(reg.active_interval))
            print("active")
            for active_interval in self.active_intervals:
                print("    " + str(active_interval))
            raise Exception("No intervals elligible for spilling at " + str(self.current_tree.ir_idx))
        
        # We could try looking for a better spot to spill the interval in
        # (eg. if we're in a loop and the interval isn't going to be used inside, we should spill the interval outside the loop)
        self.current_tree.spills.append(RegSpill(best_interval.live_in, best_interval))
        # Register will be decided at the time of restoration
        best_use_pos.used_in.restores.append(RegRestore(-1, best_interval))

        inter.live_in = best_interval.live_in
        best_interval.live_in = None
        self.active_intervals.remove(best_interval)
        self.registers[inter.live_in].active_interval = inter
        self.active_intervals.append(inter)

    # Performs LSRA on the provided ir.
    # Should be called on a freshly initialized instance of Lsra.
    # Trees in the ir should be indexed in execution order (ir_idx filled in by Ir.reindex)
    def do_linear_scan(self, ir: Ir) -> None:
        # Initialize the var intervals
        self.var_intervals = []
        for i in range(ir.local_vars):
            self.var_intervals.append(Interval(
                of=i, 
                use_positions=[], 
                live_range=LiveRange(first_write_at=ir.ir_idx_count, last_read_at=-1), 
                live_in=None
            ))

        # Find the last read, first read, and first write as well as the use positions of every local variable
        for tree in ir.tree_execution_order():
            if tree.kind == irepr.TreeKind.StLocal:
                inter: Interval = self.var_intervals[tree.operands[0]]
                loc = tree.ir_idx
                if loc < inter.live_range.first_write_at:
                    inter.live_range.first_write_at = loc
            if tree.kind == irepr.TreeKind.LdLocal:
                inter: Interval = self.var_intervals[tree.operands[0]]
                # The value is going to be last read in the parent of the LdLocal node
                loc = tree.parent.ir_idx
                if loc > inter.live_range.last_read_at:
                    inter.live_range.last_read_at = loc
                inter.use_positions.append(UsePos(belongs_to=inter, used_in=tree))
        

        # Linear scan
        for block in ir.block_execution_order():
            # TODO block boundaries with active in and active out sets + resolution
            for reg in self.registers:
                reg.active_interval = None
            for interval in self.active_intervals:
                interval.live_in = None
            self.active_intervals = []

            for tree in block.tree_execution_order():
                self.current_tree = tree

                # Restores aren't allowed to reuse operand registers
                allow_operand_reuse = self.allow_operand_reuse
                self.allow_operand_reuse = False
                self.free_intervals()

                # If the tree spills or restores intervals, we update the active interval set accordingly
                # The spill part might never be encountered, but it's implemented for the sake of completeness
                for spill in tree.spills:
                    assert spill.interval.live_in != None, "spill of interval that's not active"
                    assert spill.reg == spill.interval.live_in, "spill register and register of interval to spill don't match"
                    
                    self.active_intervals.remove(spill.interval)
                    self.registers[spill.reg].active_interval = None
                    spill.interval.live_in = None
                for restore in tree.restores:
                    assert restore.interval.live_in == None, "finding a restore reg for an interval that's already active"
                    
                    self.activate_interval(restore.interval)
                    restore.reg = restore.interval.live_in
                
                # Free intervals again, this time restoring allow_operand_reuse, so that output from trees can reuse operand registers
                self.allow_operand_reuse = allow_operand_reuse
                if allow_operand_reuse:
                    self.free_intervals()

                # Special case for LdLocal : when we use the value of a var interval, we need to activate its interval.
                if tree.kind == irepr.TreeKind.LdLocal:
                    inter: Interval = self.var_intervals[tree.operands[0]]
                    self.activate_interval(inter)
                    tree.reg = inter.live_in
                
                # In all other case : create an interval for the current tree if it produces a value
                elif tree.parent != None:
                    tree_interval = Interval(
                        of=tree,
                        use_positions=[], 
                        live_range=LiveRange(first_write_at=tree.ir_idx, last_read_at=tree.parent.ir_idx), 
                        live_in=None
                    )
                    tree_interval.use_positions.append(UsePos(belongs_to=tree_interval, used_in=tree.parent))
                    self.activate_interval(tree_interval)
                    tree.reg = tree_interval.live_in

    
