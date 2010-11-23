from . import reflect

_CLASS_ANNOTATIONS_ATTR = "_class_annotations"
_ATTRIBUTE_INJECTIONS_ATTR = "_attribute_injections"
_DEFAULT_ANNOTATION_ORDER = 100


class AnnotationError(Exception):
    pass


class MetaAnnotable(type):

    def __init__(cls, name, bases, dct):
        # Class Initialization
        method = getattr(cls, "__class__init__", None)
        if method is not None:
            method(name, bases, dct)
        # Attribute Injection
        injections = getattr(cls, _ATTRIBUTE_INJECTIONS_ATTR, None)
        if injections is not None:
            for attr, value in injections:
                setattr(cls, attr, value)
            delattr(cls, _ATTRIBUTE_INJECTIONS_ATTR)
        # Class Annotations
        annotations = getattr(cls, _CLASS_ANNOTATIONS_ATTR, None)
        if annotations is not None:
            for name, methodName, args, kwargs in annotations:
                method = getattr(cls, methodName, None)
                if method is None:
                    raise AnnotationError("Bad annotation %s set on class %s, "
                                          "method %s not found"
                                          % (name, cls, methodName))
                method(*args, **kwargs)
            delattr(cls, _CLASS_ANNOTATIONS_ATTR)
        super(MetaAnnotable, cls).__init__(name, bases, dct)


class Annotable(object):
    __metaclass__ = MetaAnnotable


def injectClassCallback(annotationName, depth, methodName, *args, **kwargs):
    """
    Inject an annotation for a class method to be called
    after class initialization without dealing with metaclass.

    depth parameter specify the stack depth from the class definition.
    """
    locals = reflect.class_locals(depth, annotationName)
    annotations = locals.get(_CLASS_ANNOTATIONS_ATTR, None)
    if annotations is None:
        annotations = list()
        locals[_CLASS_ANNOTATIONS_ATTR] = annotations
    annotation = (annotationName, methodName, args, kwargs)
    annotations.append(annotation)


def injectAttribute(annotationName, depth, attr, value):
    """
    Inject an attribute in a class from it's class frame.
    Use in class annnotation to create methods/properties dynamically
    at class creation time without dealing with metaclass.

    depth parameter specify the stack depth from the class definition.
    """
    locals = reflect.class_locals(depth, annotationName)
    injections = locals.get(_ATTRIBUTE_INJECTIONS_ATTR, None)
    if injections is None:
        injections = list()
        locals[_ATTRIBUTE_INJECTIONS_ATTR] = injections
    injections.append((attr, value))