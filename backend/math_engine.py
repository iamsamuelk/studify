import sympy as sp

# ── Symbols ──
x, y, z, t, s = sp.symbols('x y z t s')
SYMBOL_MAP = {'x': x, 'y': y, 'z': z, 't': t, 's': s}


def _parse(expression_str: str):
    """Safely parse a string into a SymPy expression."""
    return sp.sympify(expression_str, locals=SYMBOL_MAP)


# ── Calculus ──

def calculate_derivative(expression_str: str, variable: str = 'x') -> str:
    """Differentiate expression with respect to a variable."""
    try:
        var = SYMBOL_MAP.get(variable, x)
        expr = _parse(expression_str)
        result = sp.diff(expr, var)
        return str(result)
    except Exception as e:
        return f"Error in derivative: {str(e)}"


def calculate_indefinite_integral(expression_str: str, variable: str = 'x') -> str:
    """Compute the indefinite integral."""
    try:
        var = SYMBOL_MAP.get(variable, x)
        expr = _parse(expression_str)
        result = sp.integrate(expr, var)
        return f"{result} + C"
    except Exception as e:
        return f"Error in indefinite integral: {str(e)}"


def calculate_definite_integral(expression_str: str, variable: str = 'x',
                                lower: str = '0', upper: str = '1') -> str:
    """Compute the definite integral between two limits."""
    try:
        var = SYMBOL_MAP.get(variable, x)
        expr = _parse(expression_str)
        lower_val = _parse(lower)
        upper_val = _parse(upper)
        result = sp.integrate(expr, (var, lower_val, upper_val))
        return str(result)
    except Exception as e:
        return f"Error in definite integral: {str(e)}"


def calculate_limit(expression_str: str, variable: str = 'x',
                    point: str = '0', direction: str = '+') -> str:
    """Compute the limit of an expression as variable → point."""
    try:
        var = SYMBOL_MAP.get(variable, x)
        expr = _parse(expression_str)
        pt = _parse(point)
        result = sp.limit(expr, var, pt, direction)
        return str(result)
    except Exception as e:
        return f"Error in limit: {str(e)}"


def solve_equation(expression_str: str, variable: str = 'x') -> str:
    """Solve an equation (expression = 0) for a variable."""
    try:
        var = SYMBOL_MAP.get(variable, x)
        expr = _parse(expression_str)
        result = sp.solve(expr, var)
        return str(result)
    except Exception as e:
        return f"Error solving equation: {str(e)}"


def simplify_expression(expression_str: str) -> str:
    """Simplify a mathematical expression."""
    try:
        expr = _parse(expression_str)
        result = sp.simplify(expr)
        return str(result)
    except Exception as e:
        return f"Error simplifying: {str(e)}"


def taylor_series(expression_str: str, variable: str = 'x',
                  point: str = '0', order: int = 5) -> str:
    """Compute the Taylor series expansion."""
    try:
        var = SYMBOL_MAP.get(variable, x)
        expr = _parse(expression_str)
        pt = _parse(point)
        result = sp.series(expr, var, pt, order)
        return str(result)
    except Exception as e:
        return f"Error in Taylor series: {str(e)}"


# ── Control Systems ──

def laplace_transform(expression_str: str) -> str:
    """Compute the Laplace transform of an expression in t → s."""
    try:
        expr = _parse(expression_str)
        result, _, _ = sp.laplace_transform(expr, t, s)
        return str(result)
    except Exception as e:
        return f"Error in Laplace transform: {str(e)}"


def inverse_laplace_transform(expression_str: str) -> str:
    """Compute the inverse Laplace transform s → t."""
    try:
        expr = _parse(expression_str)
        result = sp.inverse_laplace_transform(expr, s, t)
        return str(result)
    except Exception as e:
        return f"Error in inverse Laplace: {str(e)}"


# ── Self-test ──

if __name__ == "__main__":
    print("Derivative of x**3 + 2*x :", calculate_derivative("x**3 + 2*x"))
    print("Indefinite integral of 2*x :", calculate_indefinite_integral("2*x"))
    print("Definite integral of x**2 from 0 to 3:", calculate_definite_integral("x**2", lower='0', upper='3'))
    print("Limit of sin(x)/x as x→0 :", calculate_limit("sin(x)/x"))
    print("Solve x**2 - 4 :", solve_equation("x**2 - 4"))
    print("Simplify (x**2 - 1)/(x - 1) :", simplify_expression("(x**2 - 1)/(x - 1)"))
    print("Taylor of sin(x) order 6 :", taylor_series("sin(x)", order=6))
    print("Laplace of t*exp(-t) :", laplace_transform("t*exp(-t)"))
