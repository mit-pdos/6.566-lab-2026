import inspect
import types
import builtins
import bytecode
import contextlib
import dis

from crosshair.tracers import TracingModule
from crosshair.tracers import NoTracing
from crosshair.tracers import COMPOSITE_TRACER
from crosshair.tracers import frame_stack_read
from crosshair.tracers import frame_stack_write
from crosshair.core import Patched
from crosshair.core import register_opcode_patch

BINARY_MODULO = dis.opmap.get("BINARY_MODULO", 256)
BINARY_OP = dis.opmap.get("BINARY_OP", 256)
BUILD_STRING = dis.opmap["BUILD_STRING"]
CONTAINS_OP = dis.opmap.get("CONTAINS_OP", 256)

def frame_op_arg(frame):
  return frame.f_code.co_code[frame.f_lasti + 1]

def intercept_pct(a, b):
  orig = a % b
  origa = a
  origb = b
  if isinstance(a, str):
    res = ''
    while True:
      pos = a.find('%')
      if pos < 0:
        # if res+a != orig: print('intercept_pct mismatch:', res+a, orig)
        return res + a
      res += a[0:pos]
      a = a[pos:]
      if a[1] == 's':
        if isinstance(b, tuple):
          v = b[0]
          b = b[1:]
        else:
          v = b
        res = res + str(v)
        a = a[2:]
      elif a[1] == '(':
        pos = a.find(')')
        if pos < 0:
          break
        name = a[2:pos]
        if a[pos+1] != 's':
          break
        res += str(b[name])
        a = a[pos+2:]
      else:
        break

    ## couldn't figure out this pattern..
    # print("intercept_pct: bailing out on pattern", origa)
    return orig
  else:
    return orig

def intercept_contains(a, b):
  if not isinstance(b, dict) and \
     not isinstance(b, set) and \
     not isinstance(b, list) and \
     not isinstance(b, tuple):
    return a in b

  if a is None:
    return any(k is None for k in b)
  else:
    return any(a == k for k in b)

class DeoptimizedPercentStr:
  def __init__(self, value):
    self.value = value

  def __mod__(self, other):
    with NoTracing():
      return intercept_pct(self.value, other)

class ModuloInterceptor(TracingModule):
  opcodes_wanted = frozenset([BINARY_MODULO, BINARY_OP])
  assert BINARY_MODULO != BINARY_OP

  def trace_op(self, frame, codeobj, codenum):
    left = frame_stack_read(frame, -2)
    if isinstance(left, str):
      if codenum == BINARY_OP:
        oparg = frame_op_arg(frame)
        if oparg != 6:  # modulo operator, NB_REMAINDER
          return
      frame_stack_write(frame, -2, DeoptimizedPercentStr(left))

class DeoptimizedContainment:
  def __init__(self, value):
    self.value = value

  def __contains__(self, other):
    with NoTracing():
      return intercept_contains(other, self.value)

class ContainmentInterceptor(TracingModule):
  opcodes_wanted = frozenset([CONTAINS_OP])

  def trace_op(self, frame, codeobj, codenum):
    # item = frame_stack_read(frame, -2)
    container = frame_stack_read(frame, -1)
    frame_stack_write(frame, -1, DeoptimizedContainment(container))

class BuildStringInterceptor(TracingModule):
  opcodes_wanted = frozenset([BUILD_STRING])

  def trace_op(self, frame, codeobj, codenum):
    count = frame_op_arg(frame)
    real_result = ""
    for offset in range(-(count), 0):
      substr = frame_stack_read(frame, offset)
      real_result += substr
      frame_stack_write(frame, offset, "")

    def post_op():
      frame_stack_write(frame, -1, real_result)

    COMPOSITE_TRACER.set_postop_callback(post_op, frame)

class OpcodeIntercept(contextlib.ExitStack):
  def __enter__(self):
    super().__enter__()
    self.enter_context(Patched())
    self.enter_context(COMPOSITE_TRACER)
    return self

register_opcode_patch(ModuloInterceptor())
register_opcode_patch(ContainmentInterceptor())
register_opcode_patch(BuildStringInterceptor())
